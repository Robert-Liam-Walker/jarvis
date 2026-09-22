"""System-level commands that need no screen: media keys, volume, lock, screenshot."""

from __future__ import annotations

import ctypes
import time
from pathlib import Path

VK = {
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
    "play_pause": 0xB3,
    "next_track": 0xB0,
    "previous_track": 0xB1,
}

COMMANDS: dict[str, str] = {
    "volume_up": "Turn the system volume up a few notches.",
    "volume_down": "Turn the system volume down a few notches.",
    "mute": "Mute or unmute the system audio.",
    "play_pause": "Play or pause whatever media is playing.",
    "next_track": "Skip to the next track.",
    "previous_track": "Go back to the previous track.",
    "lock": "Lock the workstation.",
    "screenshot": "Save a screenshot of the whole screen to the Pictures folder.",
}


def _tap(vk: int, times: int = 1) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.02)


def run(command: str) -> str:
    """Execute one command and return a one-line description for the log and the voice."""
    if command in ("volume_up", "volume_down"):
        _tap(VK[command], times=4)
        return "volume up" if command == "volume_up" else "volume down"
    if command in VK:
        _tap(VK[command])
        return command.replace("_", " ")
    if command == "lock":
        ctypes.WinDLL("user32").LockWorkStation()
        return "locked"
    if command == "screenshot":
        from PIL import ImageGrab

        target = Path.home() / "Pictures" / time.strftime("jarvis-%Y%m%d-%H%M%S.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(all_screens=True).save(target)
        return f"screenshot saved to {target.name}"
    raise ValueError(f"unknown system command {command!r}")
