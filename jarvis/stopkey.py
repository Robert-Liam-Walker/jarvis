"""A global stop hotkey. Ctrl+Shift+Backspace writes the stop file the port's abort check already watches."""

from __future__ import annotations

import ctypes
import os
import tempfile
import threading
from ctypes import wintypes
from pathlib import Path

MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0002, 0x0004, 0x4000
VK_BACK = 0x08
WM_HOTKEY = 0x0312
HOTKEY_ID = 0x4A31


def stop_file() -> Path:
    path = os.environ.get("CLICKER_STOP_FILE")
    if not path:
        path = str(Path(tempfile.gettempdir()) / "jarvis-stop")
        os.environ["CLICKER_STOP_FILE"] = path
    return Path(path)


def clear_stop() -> None:
    stop_file().unlink(missing_ok=True)


def request_stop() -> None:
    stop_file().write_text("stop")


def start(on_stop=None) -> threading.Thread:
    """Register the hotkey on its own thread (RegisterHotKey is per-thread) and pump its messages."""

    def loop():
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_BACK):
            print("jarvis: could not register Ctrl+Shift+Backspace; use the mouse-to-corner abort", flush=True)
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                request_stop()
                if on_stop:
                    on_stop()

    thread = threading.Thread(target=loop, name="jarvis-stopkey", daemon=True)
    thread.start()
    return thread
