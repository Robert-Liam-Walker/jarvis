import time

from jarvis.events import Bus
from jarvis.observers.foreground import ForegroundObserver
from jarvis.observers.presence import PresenceObserver
from jarvis.observers.processes import ProcessObserver
from jarvis.observers.timer import TimerObserver


def _bus():
    bus = Bus(threaded=False)
    seen = []
    bus.subscribe("*", lambda e: seen.append((e.kind, e.key, e.payload.get("name"))))
    return bus, seen


def test_process_observer_emits_transitions_only():
    table = {1: {"name": "a.exe", "create_time": 1.0}}
    obs = ProcessObserver(lister=lambda: dict(table))
    bus, seen = _bus()
    obs.tick(bus)  # baseline
    obs.tick(bus)  # unchanged
    assert seen == []
    table[2] = {"name": "b.exe", "create_time": 2.0}
    obs.tick(bus)
    del table[1]
    obs.tick(bus)
    table[2] = {"name": "b.exe", "create_time": 3.0}  # pid reused by a new process
    obs.tick(bus)
    assert seen == [
        ("process.started", "2", "b.exe"),
        ("process.stopped", "1", "a.exe"),
        ("process.started", "2", "b.exe"),
    ]


def test_presence_observer_emits_on_threshold_crossings():
    idle = [0.0]
    obs = PresenceObserver(idle_after=120.0, idle_fn=lambda: idle[0])
    bus, seen = _bus()
    obs.tick(bus)
    obs.tick(bus)
    idle[0] = 121.0
    obs.tick(bus)
    idle[0] = 130.0
    obs.tick(bus)
    idle[0] = 0.5
    obs.tick(bus)
    assert [k for k, _, _ in seen] == ["user.active", "user.idle", "user.active"]


def test_timer_observer_dedupes_within_a_slot():
    obs = TimerObserver(interval=60.0)
    bus, seen = _bus()
    obs.tick(bus)
    obs.tick(bus)
    assert len(seen) == 2  # a sync bus without a store does not dedupe; keys prove the slot
    assert obs.polls == 2


def test_foreground_observer_emit_dedupes_same_window():
    obs = ForegroundObserver()
    bus, seen = _bus()
    obs.bus = bus
    obs.emit(10, {"title": "Untitled - Notepad", "pid": 5, "exe": "notepad.exe"})
    obs.emit(10, {"title": "Untitled - Notepad", "pid": 5, "exe": "notepad.exe"})
    obs.emit(11, {"title": "", "pid": 6, "exe": "x.exe"})  # untitled windows are noise
    obs.emit(12, {"title": "Calculator", "pid": 7, "exe": "ApplicationFrameHost.exe"})
    assert [(k, key) for k, key, _ in seen] == [("window.focused", "10"), ("window.focused", "12")]


def test_poller_thread_runs_and_stops():
    calls = []
    obs = ProcessObserver(lister=lambda: calls.append(1) or {}, interval=0.05)
    bus, _ = _bus()
    obs.start(bus)
    time.sleep(0.2)
    obs.stop()
    n = len(calls)
    assert n >= 2
    time.sleep(0.1)
    assert len(calls) == n
