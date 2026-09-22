from jarvis.events import Event
from jarvis.store import Store, home


def test_home_honours_override(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "h"))
    assert home() == tmp_path / "h"


def test_event_round_trip_and_idempotent_insert(tmp_path):
    with Store(tmp_path / "j.db") as store:
        e = Event("process.stopped", "42", "processes", {"name": "notepad.exe"}, ts=100.0, dedupe_key="ps:42:1")
        first = store.append_event(e)
        again = store.append_event(e)
        assert first == 1 and again is None
        rows = store.recent_events()
        assert len(rows) == 1
        assert rows[0]["kind"] == "process.stopped" and rows[0]["payload"] == {"name": "notepad.exe"}
        assert rows[0]["dedupe_key"] == "ps:42:1"


def test_recent_events_filters_by_kind_glob_and_since(tmp_path):
    with Store(tmp_path / "j.db") as store:
        for i, kind in enumerate(["process.started", "process.stopped", "user.idle"]):
            store.append_event(Event(kind, str(i), "t", ts=float(i), dedupe_key=f"k{i}"))
        assert [r["kind"] for r in store.recent_events(kind="process.*")] == ["process.stopped", "process.started"]
        assert [r["id"] for r in store.recent_events(since_id=2)] == [3]


def test_entities_upsert_delete_and_stale(tmp_path):
    with Store(tmp_path / "j.db") as store:
        store.upsert_entity("process", "1", {"name": "a"}, ts=1.0)
        store.upsert_entity("process", "1", {"name": "b"}, ts=2.0)
        store.upsert_entity("user", "local", {"presence": "idle"}, ts=2.0)
        assert store.entities("process") == [
            {"kind": "process", "id": "1", "state": {"name": "b"}, "updated_ts": 2.0, "seen_ts": 2.0, "stale": 0}
        ]
        store.mark_stale("process")
        assert store.entities("process")[0]["stale"] == 1
        store.delete_entity("process", "1")
        assert [e["kind"] for e in store.entities()] == ["user"]


def test_tasks_status_machine_and_demotion(tmp_path):
    with Store(tmp_path / "j.db") as store:
        tid = store.create_task("monitor training", priority=2, subscriptions=[{"kind": "jupyter.kernel.idle"}])
        assert store.tasks("pending")[0]["subscriptions"] == [{"kind": "jupyter.kernel.idle"}]
        store.update_task(tid, status="active")
        assert store.demote_interrupted_tasks() == 1
        task = store.tasks(("pending",))[0]
        assert task["status"] == "pending" and task["attempts"] == 1
        try:
            store.update_task(tid, status="bogus")
        except ValueError:
            pass
        else:
            raise AssertionError("unknown status accepted")


def test_decisions_runs_approvals(tmp_path):
    with Store(tmp_path / "j.db") as store:
        did = store.record_decision("evaluate", {"action": "notify.speak"}, {"notify.speak": 0.8}, event_id=7)
        assert store.recent_decisions()[0] == {
            "id": did,
            "ts": store.recent_decisions()[0]["ts"],
            "event_id": 7,
            "task_id": None,
            "question": "evaluate",
            "answer": {"action": "notify.speak"},
            "probabilities": {"notify.speak": 0.8},
        }
        rid = store.start_run("runs/x")
        store.end_run(rid, "done")
        aid = store.ask_approval("Close the tab?")
        store.answer_approval(aid, "yes")


def test_prune_events_drops_old_rows(tmp_path):
    with Store(tmp_path / "j.db") as store:
        store.append_event(Event("timer.tick", "60", "timer", ts=1.0, dedupe_key="old"))
        store.append_event(Event("timer.tick", "60", "timer", dedupe_key="new"))
        assert store.prune_events(older_than_days=1) == 1
        assert [r["dedupe_key"] for r in store.recent_events()] == ["new"]


def test_store_survives_reopen(tmp_path):
    path = tmp_path / "j.db"
    with Store(path) as store:
        store.upsert_entity("user", "local", {"presence": "active"})
    with Store(path) as store:
        assert store.entities("user")[0]["state"] == {"presence": "active"}
