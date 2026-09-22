"""Tell the person something: spoken through the existing Speaker, and as a desktop toast."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable

TOAST_SCRIPT = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($args[0])
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Jarvis').Show($toast)
"""


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def toast(title: str, text: str) -> None:
    """Fire and forget a Windows toast through Windows PowerShell's WinRT projection."""
    xml = f"<toast><visual><binding template='ToastGeneric'><text>{_escape(title)}</text><text>{_escape(text)}</text></binding></visual></toast>"

    def run():
        try:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", TOAST_SCRIPT, xml],
                capture_output=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            print(f"jarvis: toast failed: {e}", flush=True)

    threading.Thread(target=run, name="jarvis-toast", daemon=True).start()


class Notifier:
    def __init__(self, speak: Callable[[str], None] | None = None, toasts: bool = True, echo: bool = True):
        self._speak = speak
        self.toasts = toasts
        self.echo = echo
        self.sent: list[str] = []

    def speak(self, text: str) -> None:
        self.sent.append(text)
        if self.echo and self._speak is None:
            print(f"jarvis: {text}", flush=True)
        if self._speak is not None:
            self._speak(text)

    def notify(self, text: str, title: str = "Jarvis") -> None:
        self.speak(text)
        if self.toasts:
            toast(title, text)
