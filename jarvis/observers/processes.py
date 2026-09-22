"""process.started / process.stopped from a psutil diff every two seconds. About 10 ms a poll; no UIA, no pixels."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..events import Bus, Event
from . import Poller

Lister = Callable[[], dict[int, dict[str, Any]]]


def list_processes() -> dict[int, dict[str, Any]]:
    """pid -> {name, exe, create_time} for every process the account can see."""
    import psutil

    out: dict[int, dict[str, Any]] = {}
    for proc in psutil.process_iter(["pid", "name", "exe", "create_time"]):
        info = proc.info
        if info["name"]:
            out[info["pid"]] = {"name": info["name"], "exe": info.get("exe"), "create_time": info.get("create_time")}
    return out


class ProcessObserver(Poller):
    name = "processes"
    interval = 2.0

    def __init__(self, lister: Lister | None = None, interval: float | None = None):
        super().__init__(interval)
        self.lister = lister or list_processes
        self.known: dict[int, dict[str, Any]] | None = None

    def poll(self, bus: Bus) -> None:
        current = self.lister()
        if self.known is None:  # the first poll establishes the baseline; reconcile already emitted the starts
            self.known = current
            return
        for pid, info in current.items():
            old = self.known.get(pid)
            if old is None or old.get("create_time") != info.get("create_time"):
                bus.publish(
                    Event(
                        "process.started",
                        str(pid),
                        self.name,
                        info,
                        dedupe_key=f"process.started:{pid}:{info.get('create_time')}",
                    )
                )
        for pid, info in self.known.items():
            if pid not in current:
                bus.publish(
                    Event(
                        "process.stopped",
                        str(pid),
                        self.name,
                        {"name": info.get("name"), "exe": info.get("exe")},
                        dedupe_key=f"process.stopped:{pid}:{info.get('create_time')}",
                    )
                )
        self.known = current
