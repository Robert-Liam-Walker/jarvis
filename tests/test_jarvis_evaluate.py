from dataclasses import dataclass, field

from jarvis.capabilities import default_registry
from jarvis.evaluate import Evaluator, describe
from jarvis.events import Event
from jarvis.notify import Notifier
from jarvis.rules import Rules
from jarvis.store import Store
from jarvis.world import World


@dataclass
class FakeChoice:
    choice: str
    confidence: float = 0.9
    probabilities: dict = field(default_factory=dict)


@dataclass
class FakeNoul:
    noul: float


class FakeAnswers:
    def __init__(self, answers):
        self.answers = answers


class ScriptedClient:
    def __init__(self, relevant=0.9, action="notify.speak", notify=0.8, confidence=0.9):
        self.script = (relevant, action, notify, confidence)
        self.requests = []

    def system_one(self, state, questions):
        self.requests.append((state, questions))
        relevant, action, notify, confidence = self.script
        return FakeAnswers({"relevant": FakeNoul(relevant), "action": FakeChoice(action, confidence), "notify": FakeNoul(notify)})


def _stopped(name="notepad.exe", source="processes", pid="4", missed=False, ts=None):
    payload = {"name": name}
    if missed:
        payload["missed"] = True
    return Event("process.stopped", pid, source, payload, **({"ts": ts} if ts else {}))


def _evaluator(client=None, store=None, world=None, rules=None):
    notifier = Notifier(echo=False, toasts=False)
    world = world or World()
    ev = Evaluator(
        default_registry(), world, notifier, rules or Rules(watch_processes=["notepad.exe"]), client=client, store=store
    )
    return ev, notifier


def test_describe_sentences():
    assert describe(_stopped()) == "notepad.exe has exited."
    assert describe(_stopped(missed=True)) == "notepad.exe exited while I was away."
    assert describe(Event("process.started", "1", "p", {"name": "code.exe"})) == "code.exe has started."
    assert (
        describe(Event("jupyter.kernel.died", "k", "j", {"path": "train.ipynb"}))
        == "The Jupyter kernel for train.ipynb has died."
    )


def test_code_filters_before_jev():
    ev, _ = _evaluator(client=ScriptedClient())
    assert not ev.wants(_stopped(source="jarvis"))  # the agent's own effect
    assert not ev.wants(_stopped(name="svchost.exe"))  # not watched
    assert not ev.wants(Event("timer.tick", "60", "timer"))  # uninteresting kind
    assert not ev.wants(Event("window.focused", "1", "foreground", {"title": "x"}))
    assert ev.wants(_stopped())
    assert not ev.wants(_stopped(pid="5"))  # debounced on the process name
    assert ev.client.requests == []


def test_jev_verdict_recorded_and_spoken(tmp_path):
    with Store(tmp_path / "j.db") as store:
        client = ScriptedClient(relevant=0.91, action="notify.speak", notify=0.62)
        ev, notifier = _evaluator(client=client, store=store)
        verdict = ev.handle(Event("process.stopped", "4", "processes", {"name": "notepad.exe"}, id=3))
        assert verdict.acts and verdict.source == "jev"
        assert notifier.sent == ["notepad.exe has exited."]
        state, questions = client.requests[0]
        assert set(questions) == {"relevant", "action", "notify"}
        assert set(questions["action"].criteria) == {"nothing", "notify.speak", "notify.toast"}
        assert state["watched_processes"] == ["notepad.exe"] and "world" in state
        d = store.recent_decisions()[0]
        assert d["event_id"] == 3 and d["answer"]["action"] == "notify.speak" and d["answer"]["relevant"] == 0.91


def test_jev_says_nothing_means_silence():
    ev, notifier = _evaluator(client=ScriptedClient(relevant=0.2, action="nothing"))
    verdict = ev.handle(_stopped())
    assert verdict is not None and not verdict.acts and notifier.sent == []


def test_rule_only_without_a_client_still_notifies(tmp_path):
    with Store(tmp_path / "j.db") as store:
        ev, notifier = _evaluator(store=store)
        verdict = ev.handle(_stopped())
        assert verdict.source == "rule" and notifier.sent == ["notepad.exe has exited."]
        assert store.recent_decisions()[0]["answer"]["source"] == "rule"


def test_budget_skips_but_counts():
    ev, notifier = _evaluator(client=ScriptedClient(), rules=Rules(watch_processes=["a.exe", "b.exe"], jev_calls_per_minute=1))
    ev.handle(_stopped(name="a.exe", pid="1"))
    ev.handle(_stopped(name="b.exe", pid="2"))
    assert len(notifier.sent) == 1 and ev.skipped == 1


def test_rules_watch_matching_and_file_round_trip(tmp_path):
    from jarvis import rules

    r = Rules(watch_processes=["python", "Code.exe"])
    assert r.watches("python.exe") and r.watches("code.exe") and not r.watches("svchost.exe") and not r.watches(None)
    file = tmp_path / "config.json"
    loaded = rules.load(file)
    assert file.exists() and loaded.watch_processes == rules.DEFAULT_WATCH
    file.write_text('{"watch_processes": ["x.exe"], "idle_after": 30}', encoding="utf-8")
    loaded = rules.load(file)
    assert loaded.watch_processes == ["x.exe"] and loaded.idle_after == 30 and loaded.jev_calls_per_minute == 20
    file.write_text("{not json", encoding="utf-8")
    assert rules.load(file).watch_processes == rules.DEFAULT_WATCH
