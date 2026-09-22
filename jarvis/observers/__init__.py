"""Observers turn the machine's state changes into events. Each runs on its own thread and emits on transitions only.

Every Windows import stays inside a function so the package imports cleanly on macOS CI.
"""

from __future__ import annotations

import threading
from typing import Protocol

from ..events import Bus


class Observer(Protocol):
    name: str

    def start(self, bus: Bus) -> None: ...

    def stop(self) -> None: ...


class Poller:
    """A thread that calls `poll(bus)` every `interval` seconds until stopped. `tick()` polls once, for tests."""

    name = "poller"
    interval = 2.0

    def __init__(self, interval: float | None = None):
        if interval is not None:
            self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.bus: Bus | None = None
        self.polls = 0

    def poll(self, bus: Bus) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def tick(self, bus: Bus | None = None) -> None:
        bus = bus or self.bus
        assert bus is not None, "observer not started"
        self.polls += 1
        try:
            self.poll(bus)
        except Exception as e:  # an observer that dies takes its events with it; log and carry on
            print(f"jarvis: observer {self.name} failed: {e}", flush=True)

    def start(self, bus: Bus) -> None:
        self.bus = bus
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=f"jarvis-{self.name}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(self.interval + 1.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.interval)
