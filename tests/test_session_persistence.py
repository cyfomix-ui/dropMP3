"""Session persistence round trips with isolated settings and real silent media."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QRect
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication
import dropMP3


def wait(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(.01)
    return bool(predicate())


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / '無音.wav'
        with wave.open(str(self.path), 'wb') as wav:
            wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\0\0' * 8000 * 15)
        self.windows = []
        self.patches = [patch.object(dropMP3, 'app_data_dir', return_value=self.root / 'conf')]
        for name in ('migrate_legacy_user_data', 'setup_remote_control', 'setup_tray_icon',
                     'schedule_startup_update_check'):
            self.patches.append(patch.object(dropMP3.MiniDropPlayer, name))
        for p in self.patches:
            p.start()

    def create(self):
        w = dropMP3.MiniDropPlayer()
        self.windows.append(w)
        w.audio.setMuted(True)
        w.show()
        QApplication.processEvents()
        return w

    def dispose(self, w):
        w.prepare_session_shutdown()
        w.video_thumbnail.cancel()
        w.player.shutdown()
        w.autosave_timer.stop()
        w.hide()
        w.log_window.hide()

    def tearDown(self):
        for w in self.windows:
            self.dispose(w)
            w.log_window.deleteLater()
            w.deleteLater()
        QApplication.processEvents()
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_geometry_and_all_display_modes(self):
        for mode in ('normal', 'art', 'quarter', 'one_shot'):
            with self.subTest(mode=mode):
                w = self.create()
                if w.is_art_only_mode:
                    w.exit_art_only_mode()
                if w.is_one_shot_panel_mode:
                    w.exit_one_shot_panel_mode()
                w.setGeometry(QRect(130, 140, 780, 580))
                if mode in ('art', 'quarter'):
                    w.enter_art_only_mode()
                    if mode == 'quarter':
                        w.enter_quarter_art_mode()
                elif mode == 'one_shot':
                    w.enter_one_shot_panel_mode()
                w.move(220, 230)
                expected = w.geometry()
                self.assertTrue(wait(lambda: w.settings.value('display_mode') == mode
                                     and w.settings.value('quarter_art_geometry' if mode == 'quarter' else
                                                          'art_only_geometry' if mode == 'art' else
                                                          'one_shot_geometry' if mode == 'one_shot' else
                                                          'geometry') == expected))
                self.dispose(w)
                restored = self.create()
                self.assertEqual(restored.geometry(), expected)
                self.assertEqual(restored.is_art_only_mode, mode in ('art', 'quarter'))
                self.assertEqual(restored.is_quarter_art_mode, mode == 'quarter')
                self.assertEqual(restored.is_one_shot_panel_mode, mode == 'one_shot')
                self.dispose(restored)

    def test_play_pause_stop_position_and_shutdown(self):
        for state in ('playing', 'paused', 'stopped'):
            with self.subTest(state=state):
                w = self.create()
                w.playlist = [self.path]
                w.play_index(0)
                self.assertTrue(wait(lambda: w.player.duration() > 0 and w.player.position() > 100))
                if state == 'paused':
                    w.player.pause()
                    self.assertTrue(wait(lambda: w.player.playbackState() == QMediaPlayer.PausedState))
                elif state == 'stopped':
                    w.player.stop()
                    self.assertTrue(wait(lambda: w.player.playbackState() == QMediaPlayer.StoppedState))
                w.player.setPosition(4000)
                self.assertTrue(wait(lambda: int(w.settings.value('position', 0)) >= 3900))
                self.assertEqual(w.settings.value('playback_state'), state)
                self.dispose(w)
                saved = int(w.settings.value('position'))
                restored = self.create()
                target_state = {'playing': QMediaPlayer.PlayingState, 'paused': QMediaPlayer.PausedState,
                                'stopped': QMediaPlayer.StoppedState}[state]
                self.assertTrue(wait(lambda: restored.player.playbackState() == target_state
                                     and restored.player.position() >= saved - 150))
                self.assertLess(restored.player.position(), saved + 1500)
                self.dispose(restored)

    def test_one_shot_return_and_video_preference(self):
        w = self.create()
        w.playlist = [self.path]
        w.play_index(0, autoplay=False)
        self.assertTrue(wait(lambda: w.player.duration() > 0))
        w.player.setPosition(2500)
        w.play_one_shot(self.path)
        self.assertTrue(wait(lambda: w.player.duration() > 0 and w.player.position() > 100))
        w.player.pause()
        self.assertTrue(wait(lambda: w.player.playbackState() == QMediaPlayer.PausedState))
        w.player.setPosition(6000)
        w.video_button.setChecked(True)
        self.dispose(w)
        restored = self.create()
        self.assertEqual(restored.one_shot_path, self.path)
        self.assertEqual(restored.one_shot_return_position, 2500)
        self.assertTrue(restored.player.video_enabled)
        self.assertTrue(restored.is_one_shot_panel_mode)
        self.assertTrue(wait(lambda: restored.player.playbackState() == QMediaPlayer.PausedState
                             and abs(restored.player.position() - 6000) < 150))


if __name__ == '__main__':
    unittest.main()
