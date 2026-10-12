"""Real MP4 decoding, mode switching, thumbnail and subtitle overlay checks."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer
import dropMP3


def wait(predicate, seconds=8):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(.005)
    return bool(predicate())


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg needed to generate test media")
class VideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "日本語動画.MP4"
        subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=320x180:rate=15", "-f", "lavfi", "-i",
                        "sine=frequency=440:sample_rate=48000", "-t", "12", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", str(self.path)], check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.path.with_suffix('.srt').write_text(
            "1\n00:00:00,000 --> 00:00:04,000\nMP4字幕テスト\n\n"
            "2\n00:00:04,000 --> 00:00:12,000\nシーク後の字幕\n", encoding="utf-8")
        with patch.object(dropMP3, 'app_data_dir', return_value=self.root / 'conf'), \
             patch.object(dropMP3.MiniDropPlayer, 'migrate_legacy_user_data'), \
             patch.object(dropMP3.MiniDropPlayer, 'setup_remote_control'), \
             patch.object(dropMP3.MiniDropPlayer, 'setup_tray_icon'), \
             patch.object(dropMP3.MiniDropPlayer, 'schedule_startup_update_check'):
            self.window = dropMP3.MiniDropPlayer()
        self.window.audio.setMuted(True)
        self.window.show()
        self.errors = []
        self.window.player.errorOccurred.connect(lambda _, msg: self.errors.append(msg))

    def tearDown(self):
        self.window.video_thumbnail.cancel()
        self.window.player.shutdown()
        self.window.autosave_timer.stop()
        self.window.settings_save_timer.stop()
        self.window.log_window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_mp4_audio_thumbnail_video_seek_pause_and_subtitles(self):
        w = self.window
        self.assertEqual(w.normalize_dropped_files([self.path]), [self.path])
        self.assertEqual(w.collect_audio_files(self.root), [self.path])
        w.playlist = [self.path]
        w.play_index(0)
        self.assertTrue(wait(lambda: w.player.position() > 100), self.errors)
        self.assertFalse(w.player.showing_video)
        self.assertTrue(w.remote_status_payload()["ok"])
        self.assertTrue(wait(lambda: not w.original_art_pixmap.isNull()), self.errors)
        self.assertEqual(len(w.subtitle_primary_cues), 2)
        self.assertTrue(w.subtitle_overlay.isVisible())
        w.player.pause()
        self.assertTrue(wait(lambda: w.player.playbackState() == QMediaPlayer.PausedState))
        w.player.setPosition(5000)
        self.assertTrue(wait(lambda: abs(w.player.position() - 5000) < 150))
        frames = []
        w.player.videoFrameChanged.connect(lambda im: frames.append(im))
        w.video_button.setChecked(True)
        self.assertTrue(wait(lambda: w.player.showing_video and w.player.duration() > 0))
        self.assertTrue(wait(lambda: abs(w.player.position() - 5000) < 150))
        self.assertEqual(w.player.playbackState(), QMediaPlayer.PausedState)
        w.player.play()
        self.assertTrue(wait(lambda: len(frames) > 2), self.errors)
        self.assertEqual(w.remote_status_payload()["audio_engine"], "qt-video")
        self.assertTrue(wait(lambda: w.player.position() > 5100))
        self.assertTrue(w.subtitle_overlay.isVisible())
        self.assertTrue(wait(lambda: w.subtitle_overlay.current_index == 1))
        if os.environ.get('DROPMP3_VIDEO_SCREENSHOT'):
            w.grab().save(os.environ['DROPMP3_VIDEO_SCREENSHOT'])
        position = w.player.position()
        w.video_button.setChecked(False)
        self.assertTrue(wait(lambda: not w.player.showing_video and
                            position - 150 < w.player.position() < position + 1500), self.errors)
        self.assertEqual(w.player.video_player.playbackState(), QMediaPlayer.StoppedState)
        self.assertFalse(self.errors)

    def test_video_end_advances_to_audio_and_one_shot_subtitles(self):
        w = self.window
        audio = self.root / 'next.wav'
        with wave.open(str(audio), 'wb') as f:
            f.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
            f.writeframes(b'\0' * 48000 * 2 * 8)
        w.playlist = [self.path, audio]
        w.play_index(0)
        w.video_button.setChecked(True)
        self.assertTrue(wait(lambda: w.player.showing_video and w.player.position() > 0), self.errors)
        w.player.setPosition(11500)
        self.assertTrue(wait(lambda: w.current_index == 1 and w.player.position() > 0), self.errors)
        self.assertFalse(w.player.showing_video)
        self.assertFalse(w.video_button.isEnabled())
        w.play_one_shot(self.path, enter_panel=False)
        self.assertTrue(wait(lambda: w.player.showing_video and w.player.position() > 0), self.errors)
        self.assertTrue(w.subtitle_overlay.isVisible())
        self.assertEqual(len(w.subtitle_primary_cues), 2)
        self.assertFalse(self.errors)

    def test_thumbnail_cancellation_and_audio_track_after_video(self):
        w = self.window
        w.video_thumbnail.load(self.path)
        w.video_thumbnail.cancel()
        results = []
        w.video_thumbnail.ready.connect(lambda *args: results.append(args))
        wait(lambda: False, .15)
        self.assertFalse(results)
        w.playlist = [self.path]
        w.play_index(0)
        w.video_button.setChecked(True)
        self.assertTrue(wait(lambda: w.player.showing_video and w.player.position() > 0), self.errors)
        w.set_media_source(self.root / 'missing.mp3', autoplay=False)
        self.assertFalse(w.player.showing_video)
        self.assertFalse(w.video_button.isEnabled())
        self.assertEqual(w.player.video_player.playbackState(), QMediaPlayer.StoppedState)


if __name__ == '__main__':
    unittest.main()
