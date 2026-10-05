"""Protect Qt's audio supply threads without adding playback buffering."""

import os
import time

from PySide6.QtCore import QObject, QTimer, QThread, Qt, Signal


class _AudioMmcssLease(QObject):
    """Register and unregister on the same native Qt renderer thread."""
    def __init__(self, runtime, tid):
        super().__init__()
        self.runtime = runtime
        self.tid = tid
        c, k, avrt = runtime.ctypes, runtime._kernel32, runtime._avrt
        task_index = c.c_ulong(0)
        self.handle = avrt.AvSetMmThreadCharacteristicsW("Audio", c.byref(task_index))
        if self.handle:
            if not avrt.AvSetMmThreadPriority(self.handle, 1):  # AVRT_PRIORITY_HIGH
                runtime.diagnostic.emit(f"[AUDIO] MMCSS priority unchanged: error={c.get_last_error()}")
            runtime.diagnostic.emit(f"[AUDIO] Registered MMCSS audio supply: tid={tid}, "
                                    f"relative priority={k.GetThreadPriority(k.GetCurrentThread())}")
        else:
            runtime.diagnostic.emit(f"[AUDIO] MMCSS registration unavailable: error={c.get_last_error()}")
        QThread.currentThread().finished.connect(self.close, Qt.DirectConnection)

    def close(self):
        if self.handle:
            success = self.runtime._avrt.AvRevertMmThreadCharacteristics(self.handle)
            self.runtime.diagnostic.emit(f"[AUDIO] Released MMCSS audio supply: tid={self.tid}, success={bool(success)}")
            self.handle = None
        self.runtime._renderer_leases.pop(self.tid, None)
        self.deleteLater()


class WindowsPlaybackRuntime(QObject):
    diagnostic = Signal(str)

    def __init__(self, parent, log):
        super().__init__(parent)
        self.log = log
        self.active = False
        self._winmm = None
        self._kernel32 = None
        self._avrt = None
        self._renderer_leases = {}
        self.diagnostic.connect(log, Qt.QueuedConnection)
        self._power_state = None
        self._last_tick = 0.0
        self._last_lag_log = 0.0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        if os.name == "nt":
            try:
                self._init_windows_api()
            except Exception as exc:
                self.log(f"[AUDIO] Scheduling support unavailable: {exc}")

    def _init_windows_api(self):
        import ctypes
        from ctypes import wintypes as w

        self.ctypes = ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        # Every HANDLE signature must be explicit on 64-bit Windows.
        k.GetCurrentProcess.argtypes = []
        k.GetCurrentProcess.restype = w.HANDLE
        k.GetCurrentProcessId.argtypes = []
        k.GetCurrentProcessId.restype = w.DWORD
        k.GetCurrentThreadId.argtypes = []
        k.GetCurrentThreadId.restype = w.DWORD
        k.GetCurrentThread.argtypes = []
        k.GetCurrentThread.restype = w.HANDLE
        k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        k.CreateToolhelp32Snapshot.restype = w.HANDLE
        k.CloseHandle.argtypes = [w.HANDLE]
        k.CloseHandle.restype = w.BOOL
        k.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenThread.restype = w.HANDLE
        k.GetThreadDescription.argtypes = [w.HANDLE, ctypes.POINTER(w.LPWSTR)]
        k.GetThreadDescription.restype = ctypes.c_long
        k.LocalFree.argtypes = [ctypes.c_void_p]
        k.LocalFree.restype = ctypes.c_void_p
        k.GetThreadPriority.argtypes = [w.HANDLE]
        k.GetThreadPriority.restype = ctypes.c_int
        k.SetThreadPriority.argtypes = [w.HANDLE, ctypes.c_int]
        k.SetThreadPriority.restype = w.BOOL

        class ThreadEntry(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("usage", w.DWORD),
                        ("tid", w.DWORD), ("pid", w.DWORD),
                        ("base", w.LONG), ("delta", w.LONG), ("flags", w.DWORD)]

        class PowerState(ctypes.Structure):
            _fields_ = [("version", w.DWORD), ("control", w.DWORD), ("state", w.DWORD)]

        self.ThreadEntry = ThreadEntry
        self.PowerState = PowerState
        self.StringPointer = w.LPWSTR
        k.Thread32First.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
        k.Thread32First.restype = w.BOOL
        k.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
        k.Thread32Next.restype = w.BOOL
        k.GetProcessInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        k.GetProcessInformation.restype = w.BOOL
        k.SetProcessInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        k.SetProcessInformation.restype = w.BOOL
        self._kernel32 = k
        avrt = ctypes.WinDLL("avrt", use_last_error=True)
        avrt.AvSetMmThreadCharacteristicsW.argtypes = [w.LPCWSTR, ctypes.POINTER(w.DWORD)]
        avrt.AvSetMmThreadCharacteristicsW.restype = w.HANDLE
        avrt.AvSetMmThreadPriority.argtypes = [w.HANDLE, ctypes.c_int]
        avrt.AvSetMmThreadPriority.restype = w.BOOL
        avrt.AvRevertMmThreadCharacteristics.argtypes = [w.HANDLE]
        avrt.AvRevertMmThreadCharacteristics.restype = w.BOOL
        self._avrt = avrt

    def protect_current_audio_renderer(self):
        # QAudioBufferOutput's direct signal runs here on Qt's AudioRenderer thread.
        # No PCM is copied, and the GUI never participates in this callback.
        if self._avrt is None or QThread.currentThread().objectName() != "QFFmpeg::AudioRenderer":
            return
        tid = self._kernel32.GetCurrentThreadId()
        if tid not in self._renderer_leases:
            self._renderer_leases[tid] = _AudioMmcssLease(self, tid)

    def set_active(self, active):
        active = bool(active)
        if active == self.active:
            return
        self.active = active
        if active:
            self._last_tick = time.perf_counter()
            self._enable_timing()
            self.refresh()
            # Qt creates replacement decoder/renderer threads asynchronously.
            QTimer.singleShot(100, self.refresh)
            self.timer.start()
        else:
            self.timer.stop()
            self._release_timing()

    def _enable_timing(self):
        if self._kernel32 is None:
            return
        c, k = self.ctypes, self._kernel32
        try:
            previous = self.PowerState(1, 0, 0)
            if k.GetProcessInformation(k.GetCurrentProcess(), 4, c.byref(previous), c.sizeof(previous)):
                # Preserve unrelated policy flags and restore the original policy at pause/stop.
                policy = self.PowerState(1, previous.control | 0x1 | 0x4,
                                         previous.state & ~(0x1 | 0x4))
                if k.SetProcessInformation(k.GetCurrentProcess(), 4, c.byref(policy), c.sizeof(policy)):
                    self._power_state = previous
                else:
                    self.log(f"[AUDIO] Power policy unchanged: error={c.get_last_error()}")
            winmm = c.WinDLL("winmm")
            winmm.timeBeginPeriod.argtypes = [c.c_uint]
            winmm.timeBeginPeriod.restype = c.c_uint
            winmm.timeEndPeriod.argtypes = [c.c_uint]
            winmm.timeEndPeriod.restype = c.c_uint
            if winmm.timeBeginPeriod(1) == 0:
                self._winmm = winmm
            self.log("[AUDIO] Playback scheduling active "
                     f"(1ms timer={self._winmm is not None}, "
                     f"power throttling disabled={self._power_state is not None})")
        except Exception as exc:
            self.log(f"[AUDIO] Playback timing setup failed: {exc}")

    def _release_timing(self):
        if self._winmm is not None:
            self._winmm.timeEndPeriod(1)
            self._winmm = None
        if self._power_state is not None:
            c, k = self.ctypes, self._kernel32
            state, self._power_state = self._power_state, None
            if not k.SetProcessInformation(k.GetCurrentProcess(), 4, c.byref(state), c.sizeof(state)):
                self.log(f"[AUDIO] Power policy restore failed: error={c.get_last_error()}")

    @staticmethod
    def is_audio_supply_thread(name):
        # Qt track type 1 is audio. Leave video, GUI, image, HTTP and WASAPI/MMCSS alone.
        return name in {"QFFmpeg::AudioRenderer", "QFFmpeg::StreamDecoder1", "QFFmpeg::Demuxer"}

    def refresh(self):
        if not self.active:
            return
        now = time.perf_counter()
        lag = now - self._last_tick - 1.0
        self._last_tick = now
        if lag > 0.15 and now - self._last_lag_log > 5:
            self._last_lag_log = now
            self.log(f"[AUDIO] Audio event-loop scheduling delay: {lag * 1000:.0f} ms")
        if self._kernel32 is None:
            return
        try:
            self._protect_supply_threads()
        except Exception as exc:
            self.log(f"[AUDIO] Audio thread scheduling failed: {exc}")

    def _protect_supply_threads(self):
        c, k = self.ctypes, self._kernel32
        snapshot = k.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        try:
            entry = self.ThreadEntry()
            entry.size = c.sizeof(entry)
            own_pid = k.GetCurrentProcessId()
            more = k.Thread32First(snapshot, c.byref(entry))
            while more:
                if entry.pid == own_pid:
                    self._protect_thread(entry.tid)
                more = k.Thread32Next(snapshot, c.byref(entry))
        finally:
            k.CloseHandle(snapshot)

    def _protect_thread(self, tid):
        lease = self._renderer_leases.get(tid)
        if lease is not None and lease.handle:
            return  # MMCSS owns the renderer's priority; never override it.
        c, k = self.ctypes, self._kernel32
        handle = k.OpenThread(0x0800 | 0x0020, False, tid)
        if not handle:  # Thread may have ended during a source/device change.
            return
        try:
            name = self.StringPointer()
            if k.GetThreadDescription(handle, c.byref(name)) < 0:
                return
            try:
                description = name.value or ""
            finally:
                k.LocalFree(c.cast(name, c.c_void_p))
            if not self.is_audio_supply_thread(description):
                return
            priority = k.GetThreadPriority(handle)
            # HIGHEST is a bounded priority boost, not REALTIME/TIME_CRITICAL.
            if priority < 2:
                if k.SetThreadPriority(handle, 2):
                    self.log(f"[AUDIO] Protected supply thread: {description}, tid={tid}, priority=2")
                else:
                    self.log(f"[AUDIO] Thread priority unchanged: {description}, error={c.get_last_error()}")
        finally:
            k.CloseHandle(handle)

    def close(self):
        self.set_active(False)
