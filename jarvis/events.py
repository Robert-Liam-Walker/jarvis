"""Events: what an observer noticed, appended to the store before anyone reacts to it.

The bus has one dispatch thread. Observers publish from their own threads; subscribers (the world
reducer, the evaluator) run one at a time on the dispatch thread, so nothing downstream needs a lock.
A duplicate event (same dedupe key) is stored as a no-op and never dispatched.
"""

from __future__ import annotations

import fnmatch
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from .store import Store

Subscriber = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    kind: str  # dotted, e.g. process.stopped, user.idle, window.focused, timer.tick
    key: str  # what the event is about within its kind: a pid, a window handle, "local"
    source: str  # which observer produced it; "jarvis" marks an effect of the agent's own action
    payload: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    dedupe_key: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.dedupe_key is None:
            object.__setattr__(self, "dedupe_key", f"{self.source}:{self.kind}:{self.key}:{self.ts:.3f}")

    @property
    def name(self) -> str:
        return self.payload.get("name") or self.key


class Bus:
    def __init__(self, store: Store | None = None, threaded: bool = True):
        self.store = store
        self.threaded = threaded
        self._subs: list[tuple[str, Subscriber]] = []
        self._q: queue.Queue[Event | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self.delivered = 0
        self.duplicates = 0

    def subscribe(self, pattern: str, fn: Subscriber) -> None:
        """`pattern` is an exact kind, a glob like `process.*`, or `*` for everything."""
        self._subs.append((pattern, fn))

    def publish(self, event: Event) -> None:
        if self.threaded and self._thread is not None:
            self._q.put(event)
        else:
            self._deliver(event)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="jarvis-bus", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        if self._thread is not None:
            self._q.put(None)
            self._thread.join(timeout)
            self._thread = None

    def drain(self, timeout: float = 2.0) -> None:
        """Wait for everything queued so far to be dispatched (tests, and orderly shutdown)."""
        if self._thread is None:
            return
        done = threading.Event()
        self._q.put(_Barrier(done))  # type: ignore[arg-type]
        done.wait(timeout)

    def _loop(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            if isinstance(item, _Barrier):
                item.done.set()
                continue
            self._deliver(item)

    def _deliver(self, event: Event) -> None:
        if self.store is not None:
            event_id = self.store.append_event(event)
            if event_id is None:
                self.duplicates += 1
                return
            event = replace(event, id=event_id)
        self.delivered += 1
        for pattern, fn in list(self._subs):
            if pattern == "*" or pattern == event.kind or fnmatch.fnmatchcase(event.kind, pattern):
                try:
                    fn(event)
                except Exception as e:  # one bad subscriber must not stop the others
                    print(f"jarvis: {getattr(fn, '__name__', fn)} failed on {event.kind}: {e}", flush=True)


@dataclass
class _Barrier:
    done: threading.Event


class Debouncer:
    """Lets one event per key through per window; the rest are reported as suppressed."""

    def __init__(self, window: float = 5.0):
        self.window = window
        self._last: dict[str, float] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        last = self._last.get(key)
        if last is not None and now - last < self.window:
            return False
        self._last[key] = now
        return True


class TokenBucket:
    """A per-minute budget for Jev calls. Overflow is skipped, never queued forever."""

    def __init__(self, per_minute: int = 20):
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.tokens = self.capacity
        self._stamp = time.monotonic()

    def take(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self.tokens = min(self.capacity, self.tokens + max(0.0, now - self._stamp) * self.rate)
        self._stamp = now
        if self.tokens < 1.0:
            return False
        self.tokens -= 1.0
        return True
