import time

from jarvis.events import Bus, Debouncer, Event, TokenBucket
from jarvis.store import Store
from jarvis.world import World


def test_event_default_dedupe_key_and_name():
    e = Event("process.started", "5", "processes", {"name": "notepad.exe"}, ts=12.5)
    assert e.dedupe_key == "processes:process.started:5:12.500"
    assert e.name == "notepad.exe"
    assert Event("timer.tick", "60", "timer").name == "60"


def test_bus_subscribe_patterns_sync():
    bus = Bus(threaded=False)
    seen: list[tuple[str, str]] = []
    bus.subscribe("process.*", lambda e: seen.append(("glob", e.kind)))
    bus.subscribe("user.idle", lambda e: seen.append(("exact", e.kind)))
    bus.subscribe("*", lambda e: seen.append(("all", e.kind)))
    bus.publish(Event("process.stopped", "1", "t"))
    bus.publish(Event("user.idle", "local", "t"))
    bus.publish(Event("timer.tick", "60", "t"))
    assert seen == [
        ("glob", "process.stopped"),
        ("all", "process.stopped"),
        ("exact", "user.idle"),
        ("all", "user.idle"),
        ("all", "timer.tick"),
    ]


def test_bus_stores_before_dispatch_and_skips_duplicates(tmp_path):
    with Store(tmp_path / "j.db") as store:
        bus = Bus(store, threaded=False)
        ids: list[int | None] = []
        bus.subscribe("*", lambda e: ids.append(e.id))
        e = Event("process.stopped", "1", "t", dedupe_key="same")
        bus.publish(e)
        bus.publish(e)
        assert ids == [1] and bus.delivered == 1 and bus.duplicates == 1


def test_bus_threaded_dispatch_and_drain(tmp_path):
    with Store(tmp_path / "j.db") as store:
        bus = Bus(store)
        bus.start()
        got: list[str] = []
        bus.subscribe("*", lambda e: got.append(e.kind))
        for i in range(5):
            bus.publish(Event("timer.tick", str(i), "t", dedupe_key=f"t{i}"))
        bus.drain()
        assert got == ["timer.tick"] * 5
        bus.stop()


def test_bad_subscriber_does_not_stop_others(capsys):
    bus = Bus(threaded=False)

    def boom(e):
        raise RuntimeError("no")

    seen = []
    bus.subscribe("*", boom)
    bus.subscribe("*", lambda e: seen.append(e.kind))
    bus.publish(Event("user.active", "local", "t"))
    assert seen == ["user.active"] and "boom failed" in capsys.readouterr().out


def test_debouncer_and_token_bucket():
    d = Debouncer(5.0)
    assert d.allow("k", now=0.0) and not d.allow("k", now=4.0) and d.allow("k", now=5.0)
    b = TokenBucket(per_minute=2)
    assert b.take(now=0.0) and b.take(now=0.0) and not b.take(now=0.0)
    assert b.take(now=30.0)  # half a minute refills one token


def _started(pid: int, name: str, ts: float = 1.0) -> Event:
    return Event("process.started", str(pid), "processes", {"name": name, "exe": None}, ts=ts, dedupe_key=f"s{pid}")


def test_world_reducers_and_snapshot():
    w = World()
    assert w.apply(_started(1, "notepad.exe"))
    assert not w.apply(_started(1, "notepad.exe"))  # same state, no change
    assert w.apply(Event("user.idle", "local", "presence", {"idle_seconds": 130.0}, ts=2.0))
    assert w.user_active is False
    assert w.apply(Event("window.focused", "77", "foreground", {"title": "Untitled - Notepad", "exe": "notepad.exe", "pid": 1}))
    assert not w.apply(Event("timer.tick", "60", "timer"))
    snap = w.snapshot()
    assert snap["user"]["presence"] == "idle" and snap["processes"] == {"count": 1, "names": ["notepad.exe"]}
    assert snap["foreground"]["title"] == "Untitled - Notepad" and snap["jupyter"] is None
    assert w.apply(Event("process.stopped", "1", "processes", {"name": "notepad.exe"}))
    assert w.snapshot()["processes"]["count"] == 0
    assert w.apply(Event("jupyter.kernel.busy", "k1", "jupyter", {"path": "train.ipynb"}))
    assert w.apply(Event("jupyter.kernel.idle", "k1", "jupyter", {"path": "train.ipynb"}))
    assert w.snapshot()["jupyter"]["k1"]["status"] == "idle"
    assert w.apply(Event("jupyter.kernel.died", "k1", "jupyter"))


def test_world_mirrors_to_store_and_reloads(tmp_path):
    with Store(tmp_path / "j.db") as store:
        w = World(store)
        w.apply(_started(9, "python.exe"))
        w.apply(Event("user.active", "local", "presence"))
    with Store(tmp_path / "j.db") as store:
        again = World(store)
        assert again.get("process", "9")["name"] == "python.exe" and again.user_active is True


def test_reconcile_emits_missed_starts_and_stops():
    w = World()
    w.apply(_started(1, "gone.exe"))
    w.apply(_started(2, "still.exe"))
    bus = Bus(threaded=False)
    bus.subscribe("*", w.apply)
    kinds: list[tuple[str, str]] = []
    bus.subscribe("process.*", lambda e: kinds.append((e.kind, e.payload["name"])))
    live = {2: {"name": "still.exe", "create_time": 5.0}, 3: {"name": "new.exe", "create_time": 6.0}}
    assert w.reconcile(bus, live, now=time.time()) == (1, 1)
    assert sorted(kinds) == [("process.started", "new.exe"), ("process.stopped", "gone.exe")]
    assert sorted(w.snapshot()["processes"]["names"]) == ["new.exe", "still.exe"]
