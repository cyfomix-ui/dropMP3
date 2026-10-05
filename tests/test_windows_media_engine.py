"""Real Windows Media Foundation playback through the production IPC worker."""

import os
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from audio_process import AudioProcessPlayer


@unittest.skipUnless(os.name == "nt", "Windows playback")
class WindowsPlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.paths = [Path(self.temp.name) / name for name in ["日本語 first.wav", "next.wav"]]
        for path in self.paths:
            with wave.open(str(path), "wb") as f:
                f.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
                f.writeframes(b"\0" * 48000 * 4 * 4)
        with patch.dict(os.environ, {"DROPMP3_AUDIO_ENGINE": "windows"}):
            self.player = AudioProcessPlayer(self.app, lambda text: None)
        self.audio = QAudioOutput()
        self.audio.setMuted(True)
        self.player.setAudioOutput(self.audio)
        self.errors = []
        self.player.errorOccurred.connect(lambda _, text: self.errors.append(text))
        self.assertTrue(self.wait(lambda: self.player.worker_pid > 0, 10))
        self.assertEqual(self.player.engine, "windows")

    def tearDown(self):
        self.player.shutdown()
        self.player.deleteLater()
        self.audio.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait(self, predicate, seconds=4):
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(.002)
        return bool(predicate())

    def start(self, index=0):
        start = time.perf_counter()
        self.player.setSource(QUrl.fromLocalFile(str(self.paths[index])))
        self.player.play()
        self.assertTrue(self.wait(lambda: self.player.position() > 0), self.errors)
        self.assertEqual(self.player.engine, "windows", "Unexpected Qt fallback")
        return (time.perf_counter() - start) * 1000

    def test_unicode_next_track_and_repeated_source_start_without_prebuffer_wait(self):
        pid = self.player.worker_pid
        times = [self.start(i) for i in [0, 1, 1, 0]]
        self.assertLess(max(times[1:]), 500)
        self.assertEqual(self.player.worker_pid, pid)
        self.assertFalse(self.errors)
        print("native_position_started_ms:", [round(t, 1) for t in times])

    def test_seek_before_open_pause_resume_and_stop(self):
        p = self.player
        p.setSource(QUrl.fromLocalFile(str(self.paths[0])))
        p.setPosition(2000)
        p.play()
        self.assertTrue(self.wait(lambda: p.duration() > 0 and p.position() > 2100), self.errors)
        p.pause()
        self.assertTrue(self.wait(lambda: p.playbackState() == QMediaPlayer.PausedState))
        position = p.position()
        self.wait(lambda: False, .15)
        self.assertLess(abs(p.position() - position), 50)
        p.play()
        self.assertTrue(self.wait(lambda: p.playbackState() == QMediaPlayer.PlayingState and p.position() > position + 100))
        p.stop()
        self.assertTrue(self.wait(lambda: p.playbackState() == QMediaPlayer.StoppedState))
        self.assertFalse(self.errors)

    def test_end_of_media_starts_next_track(self):
        self.start()
        ended = []
        def status(value):
            if value == QMediaPlayer.EndOfMedia:
                ended.append(time.perf_counter())
                self.player.setSource(QUrl.fromLocalFile(str(self.paths[1])))
                self.player.play()
        self.player.mediaStatusChanged.connect(status)
        self.player.setPosition(3750)
        self.assertTrue(self.wait(lambda: bool(ended) and 0 < self.player.position() < 1000))
        delay = (time.perf_counter() - ended[0]) * 1000
        self.assertLess(delay, 500)
        self.assertEqual(self.player.engine, "windows")
        print(f"native_natural_end_next_position_ms: {delay:.1f}")

    def test_gui_python_busy_does_not_stop_native_playback(self):
        self.start()
        before = self.player.position()
        end = time.perf_counter() + .8
        while time.perf_counter() < end:
            sum(range(10000))
        self.app.processEvents()
        self.assertTrue(self.wait(lambda: self.player.position() >= before + 700))
        self.assertEqual(self.player.playbackState(), QMediaPlayer.PlayingState)
        self.assertFalse(self.errors)

    def test_invalid_file_reports_error_after_codec_fallback(self):
        self.player.setSource(QUrl.fromLocalFile(str(Path(self.temp.name) / "missing.mp3")))
        self.player.play()
        self.assertTrue(self.wait(lambda: bool(self.errors)))
        self.assertEqual(self.player.mediaStatus(), QMediaPlayer.InvalidMedia)

    def test_selected_audio_endpoint_matches_windows_endpoint(self):
        from windows_media_engine import WindowsMediaEngine
        engine = WindowsMediaEngine()
        engine.setMuted(True)
        errors = []
        engine.errorOccurred.connect(lambda _, text: errors.append(text))
        try:
            for device in QMediaDevices.audioOutputs():
                endpoint = bytes(device.id()).decode().lower()
                engine.setDevice(device)
                self.assertTrue(self.wait(lambda: not engine._tasks), errors)
                self.assertFalse(errors)
                self.assertIsNotNone(engine.native.audio_device)
                self.assertIn(endpoint, engine.native.audio_device.id.lower())
        finally:
            engine.close()


if __name__ == "__main__":
    unittest.main()
