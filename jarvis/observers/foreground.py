"""window.focused from SetWinEventHook(EVENT_SYSTEM_FOREGROUND): push, not poll, and no UI Automation.

Same shape as stopkey.py: the hook belongs to the thread that installed it, so that thread pumps
messages until it is told to quit.
"""

from __future__ import annotations

import contextlib
import threading

from ..events import Bus, Event

EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WM_QUIT = 0x0012


def describe_window(hwnd: int) -> dict:
    """title, pid and exe of a top-level window, through Win32 and psutil only."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = None
    try:
        import psutil

        exe = psutil.Process(pid.value).name()
    except Exception:
        pass
    return {"title": buf.value, "pid": pid.value, "exe": exe}


class ForegroundObserver:
    name = "foreground"

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self.bus: Bus | None = None
        self.last: tuple[int, str] | None = None

    def emit(self, hwnd: int, info: dict | None = None) -> None:
        """Publish one focus change. Separated from the hook so tests can drive it."""
        assert self.bus is not None
        info = info or describe_window(hwnd)
        if not info.get("title"):
            return
        current = (hwnd, info["title"])
        if current == self.last:
            return
        self.last = current
        self.bus.publish(Event("window.focused", str(hwnd), self.name, info))

    def start(self, bus: Bus) -> None:
        self.bus = bus
        self._thread = threading.Thread(target=self._loop, name="jarvis-foreground", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is not None and self._thread_id is not None:
            import ctypes

            ctypes.WinDLL("user32").PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(2.0)
        self._thread = None

    def _loop(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._thread_id = kernel32.GetCurrentThreadId()
        proto = ctypes.WINFUNCTYPE(
            None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD
        )

        def on_event(hook, event, hwnd, id_object, id_child, thread, ms):
            if hwnd:
                try:
                    self.emit(int(hwnd))
                except Exception as e:
                    print(f"jarvis: foreground observer failed: {e}", flush=True)

        callback = proto(on_event)  # kept referenced for the hook's lifetime
        hook = user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, callback, 0, 0, WINEVENT_OUTOFCONTEXT
        )
        if not hook:
            print("jarvis: could not install the foreground hook", flush=True)
            return
        with contextlib.suppress(Exception):
            self.emit(user32.GetForegroundWindow())
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWinEvent(hook)
