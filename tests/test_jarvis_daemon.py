from jarvis.cli import main
from jarvis.daemon import Supervisor
from jarvis.events import Bus, Event
from jarvis.observers.presence import PresenceObserver
from jarvis.observers.processes import ProcessObserver
from jarvis.rules import Rules
from jarvis.store import Store
from jarvis.world import World


class ManualProcesses(ProcessObserver):
    """Ticked by the test, never by a thread."""

    def start(self, bus):
        self.bus = bus


class ManualPresence(PresenceObserver):
    def start(self, bus):
        self.bus = bus


def _supervisor(home, table, idle, rules=None, client=None):
    said = []
    obs = [ManualProcesses(lister=lambda: dict(table)), ManualPresence(idle_after=120, idle_fn=lambda: idle[0])]
    sup = Supervisor(
        home=home,
        client=client,
        speak=said.append,
        observers=obs,
        rules=rules or Rules(watch_processes=["notepad.exe"], toasts=False),
        lister=lambda: dict(table),
        threaded=False,
    )
    return sup, said, obs


def test_supervisor_reconciles_notifies_and_survives_restart(tmp_path):
    table = {1: {"name": "explorer.exe", "create_time": 1.0}, 2: {"name": "notepad.exe", "create_time": 2.0}}
    idle = [500.0]
    sup, said, (procs, presence) = _supervisor(tmp_path, table, idle)
    sup.start()
    assert sup.world.snapshot()["processes"]["count"] == 2  # reconcile populated the world from nothing
    procs.tick()
    presence.tick()
    assert sup.world.user_active is False
    assert said == []  # already-running watched processes are not announced on a cold start
    del table[2]
    procs.tick()
    table[4] = {"name": "notepad.exe", "create_time": 4.0}
    procs.tick()
    assert said == ["notepad.exe has exited.", "notepad.exe has started."]
    assert sup.status()["decisions"] == 2
    sup.stop()

    # while the daemon was down: explorer and notepad 4 exited, a new notepad 5 started
    table.clear()
    table.update({5: {"name": "notepad.exe", "create_time": 5.0}})
    sup2, said2, _ = _supervisor(tmp_path, table, idle)
    sup2.start()
    assert sup2.world.snapshot()["processes"]["names"] == ["notepad.exe"]
    events = [(e["kind"], e["source"]) for e in sup2.store.recent_events(kind="process.*", limit=3)]
    assert ("process.stopped", "reconcile") in events and ("process.started", "reconcile") in events
    # explorer was not watched; the missed notepad exit is reported, the catch-up start is not
    assert said2 == ["notepad.exe exited while I was away."]
    sup2.stop()


def test_interrupted_task_is_demoted_on_start(tmp_path):
    with Store(tmp_path / "jarvis.db") as store:
        tid = store.create_task("monitor training")
        store.update_task(tid, status="active")
    sup, _, _ = _supervisor(tmp_path, {}, [0.0])
    sup.start()
    task = sup.store.tasks("pending")[0]
    assert task["id"] == tid and task["attempts"] == 1
    sup.stop()


def test_utterance_is_recorded_as_an_event(tmp_path):
    sup, said, _ = _supervisor(tmp_path, {}, [0.0])
    sup.start()
    sup.publish("user.utterance", "local", "voice", {"text": "open notepad"})
    assert sup.store.recent_events(kind="user.utterance")[0]["payload"] == {"text": "open notepad"}
    assert said == []
    sup.stop()


def test_status_command_reads_the_store_without_a_daemon(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    with Store(tmp_path / "jarvis.db") as store:
        bus = Bus(store, threaded=False)
        world = World(store)
        bus.subscribe("*", world.apply)
        bus.publish(Event("process.started", "9", "processes", {"name": "python.exe"}))
        bus.publish(Event("user.idle", "local", "presence", {"idle_seconds": 300}))
        bus.publish(Event("window.focused", "1", "foreground", {"title": "train.ipynb - VS Code", "exe": "Code.exe"}))
        store.create_task("monitor training")
    main(["status", "--events", "5"])
    out = capsys.readouterr().out
    assert "user: idle" in out and "processes: 1 known" in out and "train.ipynb - VS Code" in out
    assert "#1 pending 'monitor training'" in out and "process.started" in out and "python.exe" in out
