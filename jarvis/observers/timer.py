"""timer.tick every minute, so standing tasks with a schedule have something to wake on."""

from __future__ import annotations

import time

from ..events import Bus, Event
from . import Poller


class TimerObserver(Poller):
    name = "timer"
    interval = 60.0

    def poll(self, bus: Bus) -> None:
        now = time.time()
        slot = int(now // self.interval)
        bus.publish(
            Event(
                "timer.tick",
                str(int(self.interval)),
                self.name,
                {"slot": slot},
                ts=now,
                dedupe_key=f"timer.tick:{self.interval}:{slot}",
            )
        )
