"""Exercise subtitle retries through real Qt child processes, with isolated output."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QWidget, QPlainTextEdit, QPushButton
import dropMP3


class Harness(QWidget):
    run_subtitle_request = dropMP3.MiniDropPlayer.run_subtitle_request

    def __init__(self, root, mode):
        super().__init__()
        self.conf_dir = root
        self.whisper_dialogs = []
        self.mode = mode
        self.updates = 0

    def find_whisper_command(self):
        return sys.executable, [str(self.conf_dir / "fake.py"), self.mode], sys.executable

    def subtitle_output_paths(self, path):
        return (self.conf_dir / "srt" / (path.stem + ".srt"),
                self.conf_dir / "srt" / (path.stem + ".srt2"))

    def subtitle_language_label(self, lang):
        return lang

    def position_dialog_over_player(self, *args):
        pass

    def translate_or_copy_subtitle(self, src, dest, *args):
        dest.write_bytes(src.read_bytes())

    def suspected_subtitle_lines(self, text):
        return []

    def invalidate_subtitle_status(self, path):
        self.updates += 1

    def update_playlist_panel(self):
        pass

    def current_media_path(self):
        return None


FAKE = '''import sys, time
from pathlib import Path
mode = sys.argv[1]
root = Path(__file__).parent
with (root / "attempts").open("a") as f:
    f.write(repr(sys.argv[2:]) + "\\n")
cpu = "--device" in sys.argv
if mode == "cancel":
    print("CUDA error: no kernel image is available", flush=True)
    time.sleep(10)
if mode == "split" and not cpu:
    print("CUDA error: no kernel ima", end="", flush=True)
    time.sleep(.15)
    print("ge is available", flush=True)
    sys.exit(1)
if mode == "unrelated":
    print("FileNotFoundError: ffmpeg not found", flush=True)
    sys.exit(1)
if mode in ("gpu", "both_fail", "zero") and (not cpu or mode == "both_fail"):
    print("CUDA out of memory", flush=True)
    sys.exit(0 if mode == "zero" else 1)
out = Path(sys.argv[sys.argv.index("--output_dir") + 1])
out.joinpath(Path(sys.argv[2]).stem + ".srt").write_text("1\\n00:00:00,000 --> 00:00:01,000\\nHello\\n", encoding="utf-8")
'''


class SubtitleRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def exercise(self, mode, attempts, success):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "fake.py").write_text(FAKE, encoding="utf-8")
            audio = root / "song (test).mp3"
            audio.touch()
            window = Harness(root, mode)
            with patch.object(dropMP3, "app_log"):
                window.run_subtitle_request(audio, "en", "en")
                dialog = window.whisper_dialogs[0]
                proc = dialog.findChild(QProcess)
                log = dialog.findChild(QPlainTextEdit)
                close = next(b for b in dialog.findChildren(QPushButton) if b.text() == dropMP3.T("閉じる"))
                cancelled = False
                deadline = time.monotonic() + 8
                while not close.isEnabled() and time.monotonic() < deadline:
                    self.app.processEvents()
                    if mode == "cancel" and "CUDA error:" in log.toPlainText() and not cancelled:
                        next(b for b in dialog.findChildren(QPushButton) if b.text() == dropMP3.T("中止")).click()
                        cancelled = True
                    time.sleep(.005)
                if not close.isEnabled():
                    proc.kill()
                    proc.waitForFinished(2000)
                self.assertTrue(close.isEnabled(), log.toPlainText())
                self.assertEqual(proc.state(), QProcess.NotRunning)
                lines = (root / "attempts").read_text().splitlines()
                self.assertEqual(len(lines), attempts)
                if attempts == 2:
                    self.assertIn("'--device', 'cpu', '--fp16', 'False'", lines[-1])
                    self.assertIn("'--model', 'medium'", lines[-1])
                    self.assertIn("'--language', 'en'", lines[-1])
                self.assertEqual(window.updates, int(success))
                self.assertEqual(window.subtitle_output_paths(audio)[0].exists(), success)
                dialog.close()
                window.close()
                self.app.processEvents()

    def test_gpu_failure_retries_cpu(self):
        self.exercise("gpu", 2, True)

    def test_split_error_retries(self):
        self.exercise("split", 2, True)

    def test_cpu_failure_does_not_loop(self):
        self.exercise("both_fail", 2, False)

    def test_unrelated_failure_does_not_retry(self):
        self.exercise("unrelated", 1, False)

    def test_cancellation_does_not_retry(self):
        self.exercise("cancel", 1, False)

    def test_normal_success_does_not_retry(self):
        self.exercise("success", 1, True)

    def test_whisper_zero_exit_without_srt_retries(self):
        self.exercise("zero", 2, True)


if __name__ == "__main__":
    unittest.main()
