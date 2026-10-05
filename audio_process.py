"""Persistent, private IPC client for the headless audio process."""

import json
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QUrl, Signal
from PySide6.QtNetwork import QLocalServer
from PySide6.QtMultimedia import QMediaPlayer


class AudioProcessPlayer(QObject):
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)
    durationChanged = Signal("qlonglong")
    positionChanged = Signal("qlonglong")
    # Optional diagnostic tap: timestamp at actual decoding, not GUI receipt time.
    decodedAudio = Signal(float, "qlonglong")

    def __init__(self, parent, log):
        super().__init__(parent)
        self.log = log
        self._source = QUrl()
        self._position = self._duration = self._generation = 0
        self._state = QMediaPlayer.StoppedState
        self._status = QMediaPlayer.NoMedia
        self.worker_pid = 0
        self.engine = ""
        self.runtime_active = False
        self._socket = None
        self._buffer = bytearray()
        self._pending = []
        self._closing = False
        self._ready = False
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        name = "dropmp3-audio-" + uuid.uuid4().hex
        if not self.server.listen(name):
            raise RuntimeError(self.server.errorString())
        self.server.newConnection.connect(self._accept)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ForwardedErrorChannel)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYINSTALLER_SUPPRESS_SPLASH_SCREEN", "1")
        self.process.setProcessEnvironment(env)
        if getattr(sys, "frozen", False):
            self.process.start(sys.executable, ["--audio-worker", name])
        else:
            executable = Path(sys.executable)
            pythonw = executable.with_name("pythonw.exe")
            if pythonw.exists():
                executable = pythonw
            self.process.start(str(executable), [str(Path(__file__).with_name("audio_worker.py")), name])

    def _accept(self):
        socket = self.server.nextPendingConnection()
        if self._socket is not None:
            socket.abort()
            socket.deleteLater()
            return
        self._socket = socket
        socket.readyRead.connect(self._read)
        self.server.close()
        self._read()

    def _read(self):
        self._buffer.extend(bytes(self._socket.readAll()))
        while b"\n" in self._buffer:
            line, _, tail = self._buffer.partition(b"\n")
            self._buffer = bytearray(tail)
            try:
                self._event(json.loads(line))
            except (ValueError, KeyError, TypeError) as exc:
                self.log(f"[AUDIO] Invalid worker event: {exc}")

    def _event(self, event):
        kind = event["event"]
        if kind == "ready":
            self.worker_pid = int(event["pid"])
            self.engine = event.get("engine", "qt")
            self._ready = True
            self.log(f"[AUDIO] Persistent audio process ready: pid={self.worker_pid}, engine={self.engine}")
            pending, self._pending = self._pending, []
            for message in pending:
                self._write(message)
            return
        if kind == "log":
            self.log(event["message"])
            return
        if kind == "engine":
            self.engine = event["value"]
            return
        if event.get("generation") != self._generation:
            return
        if kind == "state":
            self.runtime_active = bool(event["active"])
            self._set_state(QMediaPlayer.PlaybackState(event["value"]))
        elif kind == "status":
            self.runtime_active = bool(event["active"])
            value = QMediaPlayer.MediaStatus(event["value"])
            if value != self._status:
                self._status = value
                self.mediaStatusChanged.emit(value)
        elif kind == "position":
            self._position = int(event["value"])
            self.positionChanged.emit(self._position)
        elif kind == "duration":
            self._duration = int(event["value"])
            self.durationChanged.emit(self._duration)
        elif kind == "error":
            self.errorOccurred.emit(QMediaPlayer.Error(event["value"]), event["message"])
        elif kind == "decoded":
            self.decodedAudio.emit(event["timestamp"], event["start_us"])

    def _write(self, message):
        if self._socket is not None:
            self._socket.write((json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8"))
            self._socket.flush()

    def _command(self, command, **values):
        if self._closing:
            return
        message = {"command": command, "generation": self._generation, **values}
        if self._ready:
            self._write(message)
        else:
            self._pending.append(message)

    def _set_state(self, state):
        if self._state != state:
            self._state = state
            self.playbackStateChanged.emit(state)

    def _process_error(self, error):
        if not self._closing:
            self.log(f"[AUDIO] Worker process error: {self.process.errorString()}")
            self.errorOccurred.emit(QMediaPlayer.ResourceError, self.process.errorString())

    def _finished(self, code, status):
        self.runtime_active = False
        self._ready = False
        self._set_state(QMediaPlayer.StoppedState)
        if not self._closing:
            self.errorOccurred.emit(QMediaPlayer.ResourceError, f"音声プロセスが終了しました ({code})")

    def setAudioOutput(self, audio):
        self._audio = audio
        audio.volumeChanged.connect(lambda v: self._command("volume", value=v))
        audio.mutedChanged.connect(lambda v: self._command("muted", value=v))
        audio.deviceChanged.connect(lambda: self._command("device", value=bytes(audio.device().id()).hex()))
        self._command("volume", value=audio.volume())
        self._command("muted", value=audio.isMuted())
        self._command("device", value=bytes(audio.device().id()).hex())

    def setSource(self, source):
        self._generation += 1
        self._source = QUrl(source)
        self._position = self._duration = 0
        self._status = QMediaPlayer.NoMedia
        self._command("source", value=source.toString())

    def source(self):
        return QUrl(self._source)

    def position(self):
        return self._position

    def duration(self):
        return self._duration

    def playbackState(self):
        return self._state

    def mediaStatus(self):
        return self._status

    def play(self):
        self._command("play")

    def pause(self):
        self._command("pause")

    def stop(self):
        self._command("stop")
        self._set_state(QMediaPlayer.StoppedState)

    def setPosition(self, position):
        self._position = max(0, int(position))
        self._command("seek", value=self._position)

    def enable_audio_probe(self):
        self._command("probe")

    def shutdown(self):
        if self._closing:
            return
        self._command("quit")
        self._closing = True
        if self._socket is not None:
            self._socket.disconnectFromServer()
        self.server.close()
        if self.process.state() != QProcess.NotRunning:
            if not self.process.waitForFinished(2000):
                self.process.kill()
                self.process.waitForFinished(1000)
