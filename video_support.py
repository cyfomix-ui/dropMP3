"""Optional in-process video playback alongside the isolated audio engine."""
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink

from audio_process import AudioProcessPlayer

VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm"}


class MediaProcessPlayer(QObject):
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)
    durationChanged = Signal("qlonglong")
    positionChanged = Signal("qlonglong")
    videoFrameChanged = Signal(object)
    decodedAudio = Signal(float, "qlonglong")

    def __init__(self, parent, log):
        super().__init__(parent)
        self.audio_player = AudioProcessPlayer(self, log)
        self.audio_player.decodedAudio.connect(self.decodedAudio)
        self.video_player = QMediaPlayer(self)
        self.video_sink = QVideoSink(self)
        self.video_player.setVideoSink(self.video_sink)
        self.video_sink.videoFrameChanged.connect(self._frame)
        self.active = self.audio_player
        self.video_enabled = False
        self._source = QUrl()
        self._restore = None
        self._intent = QMediaPlayer.StoppedState
        for player in (self.audio_player, self.video_player):
            for name in ("playbackStateChanged", "mediaStatusChanged", "errorOccurred",
                         "durationChanged", "positionChanged"):
                getattr(player, name).connect(
                    lambda *args, p=player, n=name: self._forward(p, n, args))

    @property
    def worker_pid(self):
        return self.audio_player.worker_pid

    @property
    def engine(self):
        return "qt-video" if self.showing_video else self.audio_player.engine

    @property
    def process(self):
        return self.audio_player.process

    @property
    def runtime_active(self):
        return self.audio_player.runtime_active

    def enable_audio_probe(self):
        self.audio_player.enable_audio_probe()

    @property
    def showing_video(self):
        return self.active is self.video_player

    def _forward(self, player, name, args):
        if player is not self.active:
            return
        if self._restore is not None and name == "mediaStatusChanged" and args[0] in (
                QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            position, self._restore = self._restore, None
            player.setPosition(position)
            if self._intent == QMediaPlayer.PlayingState:
                player.play()
            elif self._intent == QMediaPlayer.PausedState:
                player.pause()
        if name == "mediaStatusChanged" and args[0] == QMediaPlayer.EndOfMedia:
            self._intent = QMediaPlayer.StoppedState
        getattr(self, name).emit(*args)

    def _frame(self, frame):
        if self.showing_video and frame.isValid():
            image = frame.toImage()
            if not image.isNull():
                self.videoFrameChanged.emit(image)

    def setAudioOutput(self, audio):
        self.audio_player.setAudioOutput(audio)
        self.video_player.setAudioOutput(audio)

    def setVideoEnabled(self, enabled):
        self.video_enabled = bool(enabled)
        target = self._target(self._source)
        if target is self.active:
            return
        position, state = self.position(), self._intent
        self._select(target)
        self._intent = state
        self._restore = position
        self.active.setSource(self._source)
        self.active.setPosition(position)
        if state == QMediaPlayer.PlayingState:
            self.active.play()
        elif state == QMediaPlayer.PausedState:
            self.active.pause()

    def _target(self, source):
        is_video = Path(source.toLocalFile()).suffix.lower() in VIDEO_EXTS
        return self.video_player if self.video_enabled and is_video else self.audio_player

    def _select(self, target):
        previous, self.active = self.active, target
        previous.stop()
        if previous is self.video_player and target is not previous:
            previous.setSource(QUrl())

    def setSource(self, source):
        self._source = QUrl(source)
        self._restore = None
        self._intent = QMediaPlayer.StoppedState
        self._select(self._target(source))
        self.active.setSource(source)

    def source(self):
        return QUrl(self._source)

    def position(self):
        return self.active.position()

    def duration(self):
        return self.active.duration()

    def playbackState(self):
        return self.active.playbackState()

    def mediaStatus(self):
        return self.active.mediaStatus()

    def play(self):
        self._intent = QMediaPlayer.PlayingState
        self.active.play()

    def pause(self):
        self._intent = QMediaPlayer.PausedState
        self.active.pause()

    def stop(self):
        self._intent = QMediaPlayer.StoppedState
        self._restore = None
        self.active.stop()

    def setPosition(self, position):
        if self._restore is not None:
            self._restore = position
        self.active.setPosition(position)

    def shutdown(self):
        self.video_player.stop()
        self.video_player.setSource(QUrl())
        self.audio_player.shutdown()


class VideoThumbnail(QObject):
    """Decode one frame asynchronously, without an audio output or extra tools."""
    ready = Signal(object, object)

    def __init__(self, parent):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._frame)
        self.player.errorOccurred.connect(lambda *_: self.cancel())
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.cancel)
        self.path = None

    def load(self, path):
        self.cancel()
        self.path = Path(path)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.timer.start(8000)
        self.player.play()

    def _frame(self, frame):
        if self.path is None or not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        path = self.path
        self.path = None
        self.timer.stop()
        self.player.stop()
        self.ready.emit(path, image)

    def cancel(self):
        self.path = None
        self.timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
