"""Real Qt decoding and Windows scheduling regression checks (muted output)."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["DROPMP3_AUDIO_ENGINE"] = "qt"  # These tests inspect actual Qt decoded buffers.

import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer, Qt, QUrl, QObject, QEvent
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtMultimedia import QAudioBufferOutput, QMediaPlayer
import dropMP3 as app_module
from playback_runtime import WindowsPlaybackRuntime


def wait_until(predicate, timeout=3):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.002)
    return bool(predicate())


class PlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.wav = root / "first.wav"
        self.next_wav = root / "next.wav"
        for path in [self.wav, self.next_wav]:
            with wave.open(str(path), "wb") as f:
                f.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
                f.writeframes(b"\0" * 48000 * 4 * 8)
        with patch.object(app_module, "app_data_dir", return_value=root / "conf"), \
             patch.object(app_module.MiniDropPlayer, "migrate_legacy_user_data"), \
             patch.object(app_module.MiniDropPlayer, "setup_remote_control"), \
             patch.object(app_module.MiniDropPlayer, "setup_tray_icon"), \
             patch.object(app_module.MiniDropPlayer, "schedule_startup_update_check"):
            self.window = app_module.MiniDropPlayer()
        self.window.audio.setMuted(True)
        self.window.random_art_enabled = False
        self.window.playlist = [self.wav, self.next_wav]
        self.buffers = []
        self.errors = []
        self.window.player.decodedAudio.connect(lambda stamp, start: self.buffers.append((stamp, start)))
        self.window.player.enable_audio_probe()
        self.assertTrue(wait_until(lambda: self.window.player.worker_pid > 0, 10))
        self.window.player.errorOccurred.connect(lambda e, msg: self.errors.append(msg))

    def tearDown(self):
        self.window.player.stop()
        self.window.player.setSource(QUrl())
        self.window.player.shutdown()
        self.window.autosave_timer.stop()
        self.window.settings_save_timer.stop()
        self.window.log_window.close()
        self.window.deleteLater()
        QApplication.processEvents()
        self.temp.cleanup()

    def start_track(self, index=0):
        self.buffers.clear()
        start = time.perf_counter()
        self.window.play_index(index)
        self.assertTrue(wait_until(lambda: bool(self.buffers)), self.errors)
        return (self.buffers[0][0] - start) * 1000

    def test_source_has_no_python_whole_file_read(self):
        # A stuck Python file read must never be on the path to starting audio.
        with patch.object(Path, "open", side_effect=AssertionError("whole-file read")):
            self.window.set_media_source(self.wav, autoplay=True)
        self.assertEqual(self.window.player.source(), QUrl.fromLocalFile(str(self.wav)))
        self.assertTrue(wait_until(lambda: bool(self.buffers)))

    def test_next_track_first_decoded_audio_latency(self):
        first = self.start_track()
        next_time = self.start_track(1)
        self.assertLess(next_time, 500)
        print(f"first_decoded_audio_ms: first={first:.1f}, next={next_time:.1f}")
        self.assertFalse(self.errors)

    def test_pause_resume_and_timing_lifecycle(self):
        self.start_track()
        player = self.window.player
        self.assertTrue(player.runtime_active)
        self.window.toggle_play()
        self.assertTrue(wait_until(lambda: player.playbackState() == QMediaPlayer.PausedState))
        self.assertFalse(player.runtime_active)
        self.window.toggle_play()
        self.assertTrue(wait_until(lambda: player.playbackState() == QMediaPlayer.PlayingState))
        self.assertTrue(player.runtime_active)
        player.stop()
        self.assertTrue(wait_until(lambda: not player.runtime_active))

    def test_seek_and_one_shot_restore(self):
        self.start_track()
        self.window.player.setPosition(2000)
        self.window.play_one_shot(self.next_wav, enter_panel=False)
        self.assertTrue(wait_until(lambda: self.window.player.position() > 100))
        self.window.one_shot_path = None
        self.window.restore_after_one_shot()
        self.assertTrue(wait_until(lambda: self.window.player.position() >= 2000))
        self.assertEqual(self.window.player.source(), QUrl.fromLocalFile(str(self.wav)))
        self.assertFalse(self.errors)

    def test_rapid_track_changes_keep_latest_source(self):
        self.window.set_media_source(self.wav, autoplay=True)
        self.window.set_media_source(self.next_wav, autoplay=True)
        self.window.set_media_source(self.wav, autoplay=True)
        self.assertTrue(wait_until(lambda: bool(self.buffers)))
        self.assertEqual(self.window.player.source(), QUrl.fromLocalFile(str(self.wav)))
        self.assertFalse(self.errors)

    def test_repeat_switches_without_preload(self):
        self.start_track()
        self.window.repeat_mode = "all"
        self.window.on_media_status_changed(QMediaPlayer.EndOfMedia)
        self.assertEqual(self.window.current_index, 1)
        self.assertTrue(wait_until(lambda: bool(self.buffers)))
        self.window.repeat_mode = "one"
        self.window.on_media_status_changed(QMediaPlayer.EndOfMedia)
        self.assertEqual(self.window.current_index, 1)
        self.assertFalse(self.errors)

    @unittest.skipUnless(os.name == "nt", "Windows native scheduling")
    def test_real_decoder_threads_receive_priority(self):
        self.start_track()
        runtime = WindowsPlaybackRuntime(None, lambda _: None)
        self.assertTrue(wait_until(lambda: self.window.player.position() > 300))
        c, k = runtime.ctypes, runtime._kernel32
        found = {}
        bases = {}
        snapshot = k.CreateToolhelp32Snapshot(4, 0)
        self.assertNotEqual(snapshot, c.c_void_p(-1).value)
        try:
            entry = runtime.ThreadEntry()
            entry.size = c.sizeof(entry)
            more = k.Thread32First(snapshot, c.byref(entry))
            while more:
                if entry.pid == self.window.player.worker_pid:
                    handle = k.OpenThread(0x0800, False, entry.tid)
                    if handle:
                        try:
                            name = runtime.StringPointer()
                            if k.GetThreadDescription(handle, c.byref(name)) >= 0:
                                description = name.value or ""
                                k.LocalFree(c.cast(name, c.c_void_p))
                                if runtime.is_audio_supply_thread(description):
                                    found[description] = k.GetThreadPriority(handle)
                                    bases[description] = entry.base
                        finally:
                            k.CloseHandle(handle)
                more = k.Thread32Next(snapshot, c.byref(entry))
        finally:
            k.CloseHandle(snapshot)
        for name in ["QFFmpeg::AudioRenderer", "QFFmpeg::StreamDecoder1", "QFFmpeg::Demuxer"]:
            self.assertGreaterEqual(found.get(name, -1), 2, name)
        self.assertGreaterEqual(bases.get("QFFmpeg::AudioRenderer", -1), 16)
        self.assertNotEqual(self.window.player.worker_pid, os.getpid())
        self.assertTrue(self.window.player.runtime_active)

    def test_invalid_media_releases_timing(self):
        self.window.set_media_source(Path(self.temp.name) / "missing.mp3", autoplay=True)
        self.assertTrue(wait_until(lambda: self.window.player.mediaStatus() == QMediaPlayer.InvalidMedia))
        self.assertFalse(self.window.player.runtime_active)

    @unittest.skipUnless(os.name == "nt", "Windows power policy")
    def test_power_policy_restored_after_repeated_pause(self):
        runtime = WindowsPlaybackRuntime(None, lambda _: None)
        c, k = runtime.ctypes, runtime._kernel32
        def state():
            s = runtime.PowerState(1, 0, 0)
            self.assertTrue(k.GetProcessInformation(k.GetCurrentProcess(), 4, c.byref(s), c.sizeof(s)))
            return s.control, s.state
        original = state()
        for _ in range(3):
            runtime.set_active(True)
            self.assertEqual(state(), (original[0] | 5, original[1] & ~5))
            runtime.set_active(False)
            self.assertEqual(state(), original)

    def test_only_audio_supply_threads_match(self):
        for name in ["Thread (pooled)", "QFFmpeg::StreamDecoder0", "QFFmpeg::VideoRenderer",
                     "QWASAPIAudioSinkStream", "", "QFFmpeg::StreamDecoder10"]:
            self.assertFalse(WindowsPlaybackRuntime.is_audio_supply_thread(name))

    def test_display_switch_does_not_stop_or_reload_audio(self):
        self.start_track()
        source = self.window.player.source()
        with patch.object(self.window, "save_settings") as save:
            for _ in range(3):
                self.window.enter_art_only_mode()
                self.window.exit_art_only_mode()
                self.window.enter_one_shot_panel_mode()
                self.window.exit_one_shot_panel_mode()
            save.assert_not_called()
        self.assertEqual(self.window.player.source(), source)
        self.assertEqual(self.window.player.playbackState(), QMediaPlayer.PlayingState)
        self.assertTrue(self.window.updatesEnabled())
        self.assertTrue(self.window.settings_save_timer.isActive())
        self.assertFalse(self.errors)

    def test_drawer_resize_does_not_requeue_splitter_restore(self):
        self.window.show()
        self.window.drawer_open = True
        self.window.update_left_panel_visibility()
        with patch.object(self.window, "restore_main_splitter_sizes_later") as restore:
            for _ in range(10):
                self.window.update_left_panel_visibility()
            restore.assert_not_called()
        self.window.restore_main_splitter_sizes_later()
        self.assertTrue(self.window.splitter_restore_timer.isActive())
        self.window.enter_art_only_mode()
        self.assertFalse(self.window.splitter_restore_timer.isActive())

    def test_drawer_restore_is_coalesced_and_preserves_saved_ratio(self):
        self.window.show()
        self.window.resize(850, 520)
        self.window.drawer_open = True
        self.window.settings.setValue("main_splitter_sizes_json", "[320, 480]")
        self.window.update_left_panel_visibility()
        for _ in range(20):
            self.window.restore_main_splitter_sizes_later()
        with patch.object(self.window.main_splitter, "setSizes",
                          wraps=self.window.main_splitter.setSizes) as set_sizes:
            self.assertTrue(wait_until(lambda: not self.window.splitter_restore_timer.isActive()))
            self.assertEqual(set_sizes.call_count, 1)
            set_sizes.assert_called_with([320, 480])

    def test_slow_double_click_switches_display_without_pausing(self):
        self.start_track()
        label = self.window.art_label
        clicks = QSignalSpy(label.clicked)
        doubles = QSignalSpy(label.doubleClicked)
        states = QSignalSpy(self.window.player.playbackStateChanged)
        # Windows recognizes 300ms as a double click; the former 220ms timer paused first.
        with patch.object(QApplication, "doubleClickInterval", return_value=500):
            QTest.mouseClick(label, Qt.LeftButton)
            QTest.qWait(300)
            self.assertEqual(clicks.count(), 0)
            self.assertEqual(self.window.player.playbackState(), QMediaPlayer.PlayingState)
            QTest.mouseDClick(label, Qt.LeftButton)
            QTest.mouseRelease(label, Qt.LeftButton)
            QTest.qWait(600)
        self.assertTrue(self.window.is_art_only_mode)
        self.assertEqual(doubles.count(), 1)
        self.assertEqual(clicks.count(), 0)
        self.assertEqual(states.count(), 0)

    def test_single_art_click_still_pauses_once(self):
        self.start_track()
        clicks = QSignalSpy(self.window.art_label.clicked)
        with patch.object(QApplication, "doubleClickInterval", return_value=300):
            QTest.mouseClick(self.window.art_label, Qt.LeftButton)
            QTest.qWait(350)
        self.assertEqual(clicks.count(), 1)
        self.assertTrue(wait_until(lambda: self.window.player.playbackState() == QMediaPlayer.PausedState))

    def test_blocked_gui_does_not_block_decoder(self):
        self.start_track()
        self.assertTrue(wait_until(lambda: len(self.buffers) > 5))
        self.buffers.clear()
        before = time.perf_counter()
        # Hold the GUI's Python GIL and event loop for much longer than the audio sink.
        deadline = before + 0.8
        while time.perf_counter() < deadline:
            pass
        after = time.perf_counter()
        self.assertTrue(wait_until(lambda: any(b[0] >= after for b in self.buffers)))
        during = [b[0] for b in self.buffers if before <= b[0] <= after]
        self.assertGreaterEqual(len(during), 7, during)
        gaps = [b-a for a,b in zip(during, during[1:])]
        self.assertLess(max(gaps), .13)
        print(f"gui_block_s={after-before:.3f}, decoded_during_block={len(during)}, max_gap_ms={max(gaps)*1000:.1f}")

    def test_worker_reused_and_stops_on_parent_shutdown(self):
        self.start_track()
        pid = self.window.player.worker_pid
        self.start_track(1)
        self.assertEqual(self.window.player.worker_pid, pid)
        self.window.player.shutdown()
        self.assertEqual(self.window.player.process.state().value, 0)

    def test_same_source_repeat_keeps_duration(self):
        self.start_track()
        self.assertTrue(wait_until(lambda: self.window.player.duration() == 8000))
        self.start_track()
        self.assertTrue(wait_until(lambda: self.window.player.duration() == 8000))
        self.assertFalse(self.errors)

    def test_three_display_modes_keep_audio_and_normal_geometry(self):
        self.window.show()
        self.window.resize(850, 520)
        QApplication.processEvents()
        normal = self.window.geometry()
        self.start_track()
        source = self.window.player.source()
        for _ in range(2):
            self.window.on_art_double_clicked()
            self.assertTrue(self.window.is_art_only_mode)
            self.assertFalse(self.window.is_quarter_art_mode)
            self.window.on_art_double_clicked()
            QApplication.processEvents()
            self.assertTrue(self.window.is_quarter_art_mode)
            self.assertEqual((self.window.width(), self.window.height()), (128, 154))
            self.assertEqual((self.window.art_stack.width(), self.window.art_stack.height()), (128, 128))
            self.assertTrue(self.window.art_title_label.isVisible())
            self.assertFalse(self.window.small_play_button.isVisible())
            self.assertFalse(self.window.small_time_label.isVisible())
            self.window.on_art_double_clicked()
            self.assertFalse(self.window.is_art_only_mode)
            self.assertFalse(self.window.is_quarter_art_mode)
            self.assertEqual(self.window.geometry(), normal)
        self.assertEqual(self.window.player.source(), source)
        self.assertEqual(self.window.player.playbackState(), QMediaPlayer.PlayingState)

    def test_lyrics_fill_mini_art_and_stay_hidden_in_quarter(self):
        w = self.window
        w.show()
        w.subtitle_primary_cues = [(i * 1000, i * 1000 + 999, f"歌詞の行 {i}") for i in range(16)]
        w.subtitle_display_mode = 1
        w.subtitles_manually_hidden = False
        w.update_subtitle_controls()
        w.on_position_changed(7000)
        w.on_art_double_clicked()
        QApplication.processEvents()
        w.subtitle_overlay.ensure_subtitle_render_cache()
        self.assertTrue(w.subtitle_overlay.full_area)
        self.assertTrue(w.subtitle_overlay.isVisible())
        self.assertTrue(w.subtitle_overlay._render_rect.contains(w.subtitle_overlay.rect()))
        w.on_art_double_clicked()
        w.on_position_changed(8000)
        w.on_seek_move(8500)
        w.update_subtitle_controls()
        self.assertFalse(w.subtitle_overlay.isVisible())
        self.assertEqual(w.subtitle_display_mode, 1)
        w.on_art_double_clicked()
        w.on_position_changed(8000)
        self.assertFalse(w.subtitle_overlay.full_area)
        self.assertTrue(w.subtitle_overlay.isVisible())

    def test_lyrics_stop_random_art_including_hidden_or_secondary_lyrics(self):
        w = self.window
        w.random_art_enabled = True
        w.random_art_mode = True
        w.random_art_timer.start(20000)
        w.subtitle_secondary_cues = [(0, 1000, "translated lyric")]
        w.subtitle_display_mode = 0
        w.subtitles_manually_hidden = True
        with patch.object(w, "restore_original_album_art") as restore, \
             patch.object(w, "extract_album_art") as extract:
            w.update_subtitle_controls()
            restore.assert_called_once()
            w.prepare_random_art_for_current_track(True)
            w.start_random_art_mode()
            w.show_random_playlist_art()
            w.resume_random_art_timers_for_playback_play()
            extract.assert_not_called()
        self.assertTrue(w.random_art_enabled)  # Keep the user's preference for other songs.
        self.assertFalse(w.random_art_timer.isActive())
        self.assertFalse(w.random_art_delay_timer.isActive())
        w.subtitle_secondary_cues = []
        w.prepare_random_art_for_current_track(True)
        self.assertTrue(w.random_art_delay_timer.isActive())

    def test_natural_end_starts_next_track_without_worker_restart(self):
        self.start_track()
        pid = self.window.player.worker_pid
        self.window.repeat_mode = "all"
        self.buffers.clear()
        self.window.player.setPosition(7800)
        self.assertTrue(wait_until(lambda: self.window.current_index == 1))
        self.assertTrue(wait_until(lambda: any(start == 0 for _, start in self.buffers)))
        last_old = max(t for t, start in self.buffers if start >= 7800000)
        first_new = next(t for t, start in self.buffers if start == 0)
        self.assertLess(first_new - last_old, .5)
        self.assertEqual(self.window.player.worker_pid, pid)
        self.assertEqual(self.window.player.playbackState(), QMediaPlayer.PlayingState)
        print(f"natural_next_decoded_gap_ms={(first_new-last_old)*1000:.1f}")

    def test_subtitle_changes_repaint_only_the_band(self):
        frame = QFrame()
        frame.resize(1100, 900)
        layout = QGridLayout(frame)
        overlay = app_module.SubtitleOverlay()
        layout.addWidget(overlay)
        overlay.set_cues([(i * 2000, i * 2000 + 999, f"Subtitle line {i}") for i in range(10)])
        frame.show()
        QApplication.processEvents()

        class Observer(QObject):
            def __init__(self):
                super().__init__()
                self.areas = []
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Paint:
                    rect = event.region().boundingRect()
                    self.areas.append(rect.width() * rect.height())
                return False

        observer = Observer()
        overlay.installEventFilter(observer)
        for position in [2100, 4100, 5100, 6100]:
            overlay.update_position(position)
            QApplication.processEvents()
        self.assertGreaterEqual(len(observer.areas), 4)
        self.assertLess(max(observer.areas), overlay.width() * overlay.height() / 2)
        frame.close()
        frame.deleteLater()

    def test_subtitle_gap_keeps_canvas_and_clears_cached_text(self):
        window = self.window
        window.show()
        window.subtitle_display_mode = 1
        window.subtitles_manually_hidden = False
        window.subtitle_overlay.set_cues([(0, 999, "First"), (2000, 2999, "Second")])
        window.on_position_changed(500)
        self.assertFalse(window.subtitle_overlay._render_cache.isNull())
        window.on_position_changed(1500)
        self.assertTrue(window.subtitle_overlay.isVisible())
        self.assertEqual(window.subtitle_overlay.current_index, -1)
        self.assertTrue(window.subtitle_overlay._render_cache.isNull())
        window.on_position_changed(2500)
        self.assertTrue(window.subtitle_overlay.isVisible())
        self.assertEqual(window.subtitle_overlay.current_index, 1)
        self.assertFalse(window.subtitle_overlay._render_cache.isNull())
        window.subtitle_display_mode = 0
        window.on_position_changed(2600)
        self.assertFalse(window.subtitle_overlay.isVisible())

    def test_subtitle_exposure_reuses_text_layout(self):
        overlay = app_module.SubtitleOverlay()
        overlay.resize(1100, 900)
        overlay.set_cues([(i * 2000, i * 2000 + 999, f"Subtitle line {i}") for i in range(4)])
        overlay.show()
        QApplication.processEvents()
        with patch.object(overlay, "wrapped_lines", wraps=overlay.wrapped_lines) as wrap:
            overlay.update_position(2500)
            QApplication.processEvents()
            self.assertEqual(wrap.call_count, 3)
            for _ in range(5):
                overlay.update()
                QApplication.processEvents()
            self.assertEqual(wrap.call_count, 3)
            font = app_module.QFont(overlay.subtitle_font)
            font.setPointSize(font.pointSize() + 2)
            overlay.set_subtitle_style(font)
            self.assertEqual(wrap.call_count, 6)
        overlay.close()
        overlay.deleteLater()

    @unittest.skipUnless(os.name == "nt", "Windows MMCSS")
    def test_mmcss_renderer_registration_is_released_on_its_thread(self):
        runtime = WindowsPlaybackRuntime(None, lambda _: None)
        player = QMediaPlayer(self.window)
        audio = app_module.QAudioOutput(self.window)
        audio.setMuted(True)
        player.setAudioOutput(audio)
        tap = QAudioBufferOutput(self.window)
        tap.audioBufferReceived.connect(
            lambda b: runtime.protect_current_audio_renderer() if b.isValid() else None,
            Qt.DirectConnection)
        player.setAudioBufferOutput(tap)
        # The GUI/core thread must never be registered as an audio renderer.
        runtime.protect_current_audio_renderer()
        self.assertFalse(runtime._renderer_leases)
        for path in [self.wav, self.next_wav, self.wav]:
            player.setSource(QUrl.fromLocalFile(str(path)))
            player.play()
            self.assertTrue(wait_until(lambda: bool(runtime._renderer_leases)))
            self.assertTrue(all(lease.handle for lease in runtime._renderer_leases.values()))
            player.stop()
            player.setSource(QUrl())
            self.assertTrue(wait_until(lambda: not runtime._renderer_leases))
        runtime.close()


if __name__ == "__main__":
    unittest.main()
