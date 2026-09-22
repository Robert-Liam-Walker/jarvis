import threading
from dataclasses import dataclass

from jarvis import gates
from typesafe_computer_use.decide import Decision


@dataclass
class FakeChoice:
    choice: str
    confidence: float = 0.9
    probabilities: dict | None = None


@dataclass
class FakeNoul:
    noul: float


class FakeAnswers:
    def __init__(self, answers):
        self.answers = answers


class NoulClient:
    def __init__(self, p: float):
        self.p = p
        self.calls = 0

    def system_one(self, state, questions):
        self.calls += 1
        return FakeAnswers({"risky": FakeNoul(self.p)})


def _click(index: str) -> Decision:
    return Decision(kind=FakeChoice("click_item"), item=FakeChoice(index), site=FakeChoice("none"))


def test_looks_risky_by_item_text_and_hotkey(make_item):
    items = [make_item(0, "Cancel"), make_item(1, "Delete file")]
    assert gates.looks_risky(_click("0"), items) is None
    assert gates.looks_risky(_click("1"), items) == "click 'Delete file'"
    close = Decision(kind=FakeChoice("hotkey"), item=None, site=FakeChoice("none"), hotkey=FakeChoice("alt+f4"))
    assert gates.looks_risky(close, items) == "press alt+f4"
    save = Decision(kind=FakeChoice("hotkey"), item=None, site=FakeChoice("none"), hotkey=FakeChoice("ctrl+s"))
    assert gates.looks_risky(save, items) is None


def test_gate_passes_safe_actions_without_asking(screen, make_item):
    asked = []
    gate = gates.Gate(NoulClient(0.9), gates.Confirmer(ask=asked.append))
    assert gate(_click("0"), screen, [make_item(0, "Cancel")], "close the dialog") is True
    assert asked == [] and gate.client.calls == 0


def test_gate_asks_only_above_threshold(screen, make_item):
    items = [make_item(0, "Send")]
    low = gates.Gate(NoulClient(0.2), gates.Confirmer(ask=lambda q: None))
    assert low(_click("0"), screen, items, "send the email") is True

    answers = []
    confirmer = gates.Confirmer(ask=answers.append, timeout=1.0)
    confirmer.ask = lambda q: (answers.append(q), confirmer.answer("yes"))
    high = gates.Gate(NoulClient(0.9), confirmer)
    assert high(_click("0"), screen, items, "send the email") is True
    assert answers and "click 'Send'" in answers[0]

    declined = gates.Confirmer(ask=lambda q: None, timeout=0.2)
    assert gates.Gate(NoulClient(0.9), declined)(_click("0"), screen, items, "send the email") is False


def test_confirmer_accepts_spoken_yes_from_another_thread():
    confirmer = gates.Confirmer(ask=lambda q: None, timeout=2.0)
    threading.Timer(0.05, lambda: confirmer.answer("Yeah, go ahead.")).start()
    assert confirmer.confirm("Should I?") is True
    assert confirmer.answer("late") is False  # nothing pending any more


def test_confirmer_treats_no_as_no():
    confirmer = gates.Confirmer(ask=lambda q: None, timeout=2.0)
    threading.Timer(0.05, lambda: confirmer.answer("no, stop")).start()
    assert confirmer.confirm("Should I?") is False
