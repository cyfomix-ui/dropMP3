"""Windows Media Foundation playback, driven independently of the GUI.

WinRT callbacks are marshalled to the worker's Qt thread. StorageFile opens a
Unicode local path without a whole-file read or percent-encoded URI ambiguity.
"""

import asyncio
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtMultimedia import QMediaPlayer
from winrt.windows.media.playback import MediaPlayer, MediaPlayerAudioCategory
from winrt.windows.media.core import MediaSource
from winrt.windows.storage import StorageFile
from winrt.windows.media.devices import MediaDevice
from winrt.windows.devices.enumeration import DeviceInformation


class WindowsMediaEngine(QObject):
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    positionChanged = Signal("qlonglong")
    durationChanged = Signal("qlonglong")
    errorOccurred = Signal(object, str)
    nativeEvent = Signal(int, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.native = MediaPlayer()
        self.native.audio_category = MediaPlayerAudioCategory.MEDIA
        self.native.command_manager.is_enabled = False
        self.native.auto_play = False
        self._source = QUrl()
        self._media_source = None
        self._generation = 0
        self._state = QMediaPlayer.StoppedState
        self._status = QMediaPlayer.NoMedia
        self._duration = self._position = 0
        self._intent = QMediaPlayer.StoppedState
        self._opened = False
        self._seek = None
        self._handlers = []
        self._tasks = set()
        self._closed = False
        self._device_generation = 0
        self.loop = asyncio.new_event_loop()
        self.nativeEvent.connect(self._event, Qt.QueuedConnection)
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _spawn(self, coroutine):
        task = self.loop.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _tick(self):
        # Pump pending WinRT awaits without blocking the IPC/control event loop.
        self.loop.call_soon(self.loop.stop)
        self.loop.run_forever()
        if self._opened and self._intent == QMediaPlayer.PlayingState:
            position = int(self.native.playback_session.position.total_seconds() * 1000)
            if position != self._position:
                self._position = position
                self.positionChanged.emit(position)

    def _state_to(self, value):
        if value != self._state:
            self._state = value
            self.playbackStateChanged.emit(value)

    def _status_to(self, value):
        if value != self._status:
            self._status = value
            self.mediaStatusChanged.emit(value)

    def _detach(self):
        for owner, name, token in self._handlers:
            getattr(owner, 'remove_' + name)(token)
        self._handlers.clear()

    def _listen(self, owner, name, callback):
        self._handlers.append((owner, name, getattr(owner, 'add_' + name)(callback)))

    def setSource(self, source):
        self.stop()
        self._generation += 1
        generation = self._generation
        self._detach()
        self.native.source = None
        if self._media_source is not None:
            self._media_source.close()
            self._media_source = None
        self._source = QUrl(source)
        self._opened = False
        self._seek = None
        self._duration = self._position = 0
        self.durationChanged.emit(0)
        self.positionChanged.emit(0)
        if source.isEmpty():
            self._status_to(QMediaPlayer.NoMedia)
            return
        self._status_to(QMediaPlayer.LoadingMedia)
        self._listen(self.native, 'media_opened', lambda *_: self.nativeEvent.emit(generation, 'opened', ''))
        self._listen(self.native, 'media_ended', lambda *_: self.nativeEvent.emit(generation, 'ended', ''))
        self._listen(self.native, 'media_failed', lambda _, args: self.nativeEvent.emit(
            generation, 'failed', f'{args.error_message} (HRESULT {args.extended_error_code.value:#x})'))
        self._listen(self.native.playback_session, 'playback_state_changed',
                     lambda sender, _: self.nativeEvent.emit(generation, 'state', str(int(sender.playback_state))))
        self._spawn(self._open(source.toLocalFile(), generation))

    async def _open(self, path, generation):
        try:
            file = await StorageFile.get_file_from_path_async(str(Path(path)))
            if generation != self._generation or self._closed:
                return
            self._media_source = MediaSource.create_from_storage_file(file)
            self.native.source = self._media_source
            if self._intent == QMediaPlayer.PlayingState:
                self.native.play()
        except Exception as exc:
            if generation == self._generation and not self._closed:
                self._event(generation, 'failed', str(exc))

    def _event(self, generation, kind, detail):
        if self._closed or generation != self._generation:
            return
        if kind == 'opened':
            self._opened = True
            self._duration = int(self.native.playback_session.natural_duration.total_seconds() * 1000)
            self.durationChanged.emit(self._duration)
            self._status_to(QMediaPlayer.LoadedMedia)
            if self._seek is not None:
                self.native.playback_session.position = timedelta(milliseconds=self._seek)
                self._seek = None
            if self._intent == QMediaPlayer.PlayingState:
                self.native.play()
        elif kind == 'ended':
            self._intent = QMediaPlayer.StoppedState
            self._position = self._duration
            self.positionChanged.emit(self._position)
            self._state_to(QMediaPlayer.StoppedState)
            self._status_to(QMediaPlayer.EndOfMedia)
        elif kind == 'failed':
            self._intent = QMediaPlayer.StoppedState
            self._state_to(QMediaPlayer.StoppedState)
            self._status_to(QMediaPlayer.InvalidMedia)
            self.errorOccurred.emit(QMediaPlayer.ResourceError, detail)
        elif kind == 'state':
            state = int(detail)
            if state == 3 and self._intent == QMediaPlayer.PlayingState:
                self._state_to(QMediaPlayer.PlayingState)
                self._status_to(QMediaPlayer.BufferedMedia)
            elif state == 4 and self._intent == QMediaPlayer.PausedState:
                self._state_to(QMediaPlayer.PausedState)
            elif state == 2:
                self._status_to(QMediaPlayer.BufferingMedia)

    def play(self):
        self._intent = QMediaPlayer.PlayingState
        if self.native.source is not None:
            self.native.play()

    def pause(self):
        self._intent = QMediaPlayer.PausedState
        self.native.pause()
        self._state_to(QMediaPlayer.PausedState)

    def stop(self):
        self._intent = QMediaPlayer.StoppedState
        self.native.pause()
        if self._opened:
            self.native.playback_session.position = timedelta(0)
        self._position = 0
        self.positionChanged.emit(0)
        self._state_to(QMediaPlayer.StoppedState)

    def setPosition(self, value):
        self._position = max(0, int(value))
        if self._opened:
            self.native.playback_session.position = timedelta(milliseconds=self._position)
        else:
            self._seek = self._position
        self.positionChanged.emit(self._position)

    def setVolume(self, value):
        self.native.volume = float(value)

    def setMuted(self, value):
        self.native.is_muted = bool(value)

    def setDevice(self, device):
        endpoint = bytes(device.id()).decode('utf-8', errors='replace').lower()
        self._device_generation += 1
        self._spawn(self._device(endpoint, self._device_generation))

    async def _device(self, endpoint, generation):
        try:
            devices = await DeviceInformation.find_all_async_aqs_filter(MediaDevice.get_audio_render_selector())
            match = next((d for d in devices if endpoint and endpoint in d.id.lower()), None)
            if not self._closed and generation == self._device_generation:
                self.native.audio_device = match  # None follows the Windows default.
        except Exception as exc:
            if not self._closed:
                self.errorOccurred.emit(QMediaPlayer.ResourceError, f'音声出力先: {exc}')

    def duration(self):
        return self._duration

    def position(self):
        return self._position

    def mediaStatus(self):
        return self._status

    def close(self):
        self._closed = True
        self.timer.stop()
        self._detach()
        for task in list(self._tasks):
            task.cancel()
        self.loop.call_soon(self.loop.stop)
        self.loop.run_forever()
        self.loop.close()
        self.native.close()
        if self._media_source is not None:
            self._media_source.close()
            self._media_source = None
