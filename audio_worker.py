"""Headless Qt audio engine. One process per player, reused across songs."""

import json
import os
import sys
import time

from PySide6.QtCore import QCoreApplication, QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtMultimedia import QAudioBufferOutput, QAudioOutput, QMediaDevices, QMediaPlayer

from playback_runtime import WindowsPlaybackRuntime


class AudioWorker(QObject):
    decodedReady = Signal(float, "qlonglong", int)

    def __init__(self, name, app):
        super().__init__(app)
        self.app = app
        self.generation = 0
        self.closing = False
        self.buffer = bytearray()
        self.socket = QLocalSocket(self)
        self.socket.readyRead.connect(self.read)
        self.socket.disconnected.connect(app.quit)
        self.socket.errorOccurred.connect(lambda _: app.quit())
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.native_engine = False
        self.source_url = QUrl()
        self.intent = "stop"
        self.seek_position = 0
        if os.name == "nt" and os.environ.get("DROPMP3_AUDIO_ENGINE") != "qt":
            try:
                from windows_media_engine import WindowsMediaEngine
                self.player.deleteLater()
                self.player = WindowsMediaEngine(self)
                self.native_engine = True
            except Exception as exc:
                print(f"Windows playback unavailable; using Qt: {exc}", file=sys.stderr)
        self.runtime = WindowsPlaybackRuntime(self, lambda message: self.send("log", message=message))
        self.probe_enabled = False
        self.probe = QAudioBufferOutput(self)
        self.probe.audioBufferReceived.connect(self.decoded, Qt.DirectConnection)
        if not self.native_engine:
            self.player.setAudioBufferOutput(self.probe)
        self.decodedReady.connect(lambda timestamp, start_us, generation: self.send(
            "decoded", timestamp=timestamp, start_us=start_us, generation=generation), Qt.QueuedConnection)
        self.connect_player()
        self.audio.volumeChanged.connect(self.apply_volume)
        self.audio.mutedChanged.connect(self.apply_mute)
        self.audio.deviceChanged.connect(self.apply_device)
        self.socket.connected.connect(lambda: self.send("ready", pid=os.getpid(),
            engine="windows" if self.native_engine else "qt"))
        app.aboutToQuit.connect(self.close)
        self.socket.connectToServer(name)
        QTimer.singleShot(10000, self.check_connection)

    def connect_player(self):
        self.player.playbackStateChanged.connect(self.state_changed)
        self.player.mediaStatusChanged.connect(self.status_changed)
        self.player.positionChanged.connect(lambda v: self.send("position", value=v))
        self.player.durationChanged.connect(lambda v: self.send("duration", value=v))
        self.player.errorOccurred.connect(self.player_error)

    def apply_volume(self, *_):
        if self.native_engine:
            self.player.setVolume(self.audio.volume())

    def apply_mute(self, *_):
        if self.native_engine:
            self.player.setMuted(self.audio.isMuted())

    def apply_device(self, *_):
        if self.native_engine:
            self.player.setDevice(self.audio.device())

    def player_error(self, error, message):
        if self.native_engine:
            generation = self.generation
            # Leave the native callback before disposing its event subscriptions.
            QTimer.singleShot(0, lambda: self.fallback(generation, message))
        else:
            self.send("error", value=error.value, message=message)

    def fallback(self, generation, message):
        if generation != self.generation or not self.native_engine:
            return
        self.send("log", message=f"[AUDIO] Windows playback failed; Qt fallback: {message}")
        self.player.close()
        self.player.deleteLater()
        self.native_engine = False
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setAudioBufferOutput(self.probe)
        self.connect_player()
        self.send("engine", value="qt")
        self.player.setSource(self.source_url)
        self.player.setPosition(self.seek_position)
        if self.intent == "play":
            self.player.play()
        elif self.intent == "pause":
            self.player.pause()

    def check_connection(self):
        if self.socket.state() != QLocalSocket.ConnectedState:
            self.app.quit()

    def send(self, event, **values):
        if not self.closing and self.socket.state() == QLocalSocket.ConnectedState:
            message = {"event": event, "generation": self.generation, **values}
            self.socket.write((json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8"))
            self.socket.flush()

    def state_changed(self, state):
        self.runtime.set_active(state == QMediaPlayer.PlayingState)
        self.send("state", value=state.value, active=self.runtime.active)

    def status_changed(self, status):
        if self.native_engine and status == QMediaPlayer.InvalidMedia:
            return  # The fallback tries the same track before surfacing an error.
        if status in (QMediaPlayer.InvalidMedia, QMediaPlayer.NoMedia, QMediaPlayer.EndOfMedia):
            self.runtime.set_active(False)
        self.send("status", value=status.value, active=self.runtime.active)

    def read(self):
        self.buffer.extend(bytes(self.socket.readAll()))
        while b"\n" in self.buffer:
            line, _, tail = self.buffer.partition(b"\n")
            self.buffer = bytearray(tail)
            try:
                self.command(json.loads(line))
            except (ValueError, KeyError, TypeError) as exc:
                self.send("error", value=QMediaPlayer.ResourceError.value, message=str(exc))

    def command(self, message):
        command = message["command"]
        if command == "source":
            # Stop the previous decoder with its previous generation before switching.
            self.player.stop()
            self.generation = int(message["generation"])
            self.intent = "stop"
            self.seek_position = 0
            self.source_url = QUrl(message["value"])
            self.player.setSource(self.source_url)
            # Qt does not re-emit duration/status when repeating the same URL.
            self.send("duration", value=self.player.duration())
            self.send("position", value=self.player.position())
            self.status_changed(self.player.mediaStatus())
        elif command in ("volume", "muted", "device", "quit", "probe"):
            if command == "volume":
                self.audio.setVolume(float(message["value"]))
            elif command == "muted":
                self.audio.setMuted(bool(message["value"]))
            elif command == "device":
                device_id = bytes.fromhex(message["value"])
                device = next((d for d in QMediaDevices.audioOutputs() if bytes(d.id()) == device_id),
                              QMediaDevices.defaultAudioOutput())
                self.audio.setDevice(device)
            elif command == "quit":
                self.app.quit()
            elif command == "probe":
                self.probe_enabled = True
        elif message["generation"] == self.generation:
            if command == "play":
                self.intent = "play"
                self.player.play()
            elif command == "pause":
                self.intent = "pause"
                self.player.pause()
            elif command == "stop":
                self.intent = "stop"
                self.player.stop()
            elif command == "seek":
                self.seek_position = int(message["value"])
                self.player.setPosition(int(message["value"]))

    def decoded(self, buffer):
        if buffer.isValid():
            self.runtime.protect_current_audio_renderer()
            if self.probe_enabled:
                self.decodedReady.emit(time.perf_counter(), buffer.startTime(), self.generation)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.player.stop()
        self.player.setSource(QUrl())
        if self.native_engine:
            self.player.close()
        self.runtime.close()


def run_audio_worker(name):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        # The headless process only handles playback. Protect its control loop too:
        # otherwise opening the next source can starve before decoder threads exist.
        # HIGH remains below real-time and the WASAPI/MMCSS render thread.
        kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x80)  # HIGH, never REALTIME
    app = QCoreApplication([sys.argv[0], "--audio-worker"])
    worker = AudioWorker(name, app)
    return app.exec()


if __name__ == "__main__":
    sys.exit(run_audio_worker(sys.argv[1]))
