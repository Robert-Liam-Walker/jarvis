"""user.idle / user.active from GetLastInputInfo. The policy layer reads this before any GUI action."""

from __future__ import annotations

from collections.abc import Callable

from ..events import Bus, Event
from . import Poller


def idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input on this session."""
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = (("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD))

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return max(0, (kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


class PresenceObserver(Poller):
    name = "presence"
    interval = 5.0

    def __init__(self, idle_after: float = 120.0, idle_fn: Callable[[], float] | None = None, interval: float | None = None):
        super().__init__(interval)
        self.idle_after = idle_after
        self.idle_fn = idle_fn or idle_seconds
        self.state: str | None = None

    def poll(self, bus: Bus) -> None:
        idle = self.idle_fn()
        state = "idle" if idle >= self.idle_after else "active"
        if state == self.state:
            return
        self.state = state
        bus.publish(Event(f"user.{state}", "local", self.name, {"idle_seconds": round(idle, 1)}))
