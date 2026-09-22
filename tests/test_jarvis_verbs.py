import sys
from dataclasses import dataclass

import pytest

from typesafe_computer_use import actions, decide
from typesafe_computer_use.models import Field


@dataclass
class FakeChoice:
    choice: str
    confidence: float = 0.9
    probabilities: dict | None = None


class FakeAnswers:
    def __init__(self, answers):
        self.answers = answers


class FakeClient:
    def __init__(self, answer: str):
        self.answer = answer
        self.calls = []

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        return FakeAnswers({name: FakeChoice(self.answer) for name in questions})


def test_new_verbs_only_offered_when_catalogs_exist():
    plain = decide.fixed_actions("Google Chrome", None)
    assert not {"open_app", "switch_window", "hotkey"} & set(plain)
    jarvis = decide.fixed_actions("Google Chrome", None, apps=True, windows=True, hotkeys=True)
    assert {"open_app", "switch_window", "hotkey"} <= set(jarvis)


def test_decision_confidence_uses_secondary_answer():
    d = decide.Decision(kind=FakeChoice("open_app", 0.9), item=None, site=FakeChoice("none"), app=FakeChoice("notepad", 0.3))
    assert d.confidence == pytest.approx(0.3)
    assert d.chosen == "open_app"


def _ctx(client, candidates):
    return actions.Context(
        goal="write hello",
        browser="Google Chrome",
        email=None,
        typesafe=client,
        writer=None,
        history=[],
        text_candidates=tuple(candidates),
    )


def _screen_with_text_field(screen):
    return type(screen)(
        image=screen.image,
        scale=screen.scale,
        app="Notepad",
        field=Field("AXTextArea", "Text editor", "", "", 0, 0, 10, 10),
        url=None,
    )


def test_single_candidate_skips_jev(screen):
    client = FakeClient("0")
    text = actions._text_from_utterance(_ctx(client, ["hello"]), _screen_with_text_field(screen))
    assert text == "hello"
    assert client.calls == []


def test_multiple_candidates_ask_jev_once(screen):
    client = FakeClient("1")
    text = actions._text_from_utterance(_ctx(client, ["hello in notepad", "hello"]), _screen_with_text_field(screen))
    assert text == "hello"
    assert len(client.calls) == 1
    assert "none" in client.calls[0][1]["text"].criteria


def test_type_text_refuses_without_field_or_writer(screen):
    assert actions._type_text(None, screen, [], _ctx(FakeClient("0"), [])) == "type_text refused: no text field is focused"
    refused = actions._type_text(None, _screen_with_text_field(screen), [], _ctx(FakeClient("none"), []))
    assert refused == "type_text refused: no writer available"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows adapter")
def test_launch_app_rejects_shell_metacharacters():
    from typesafe_computer_use import windows
    from typesafe_computer_use.models import Abort

    with pytest.raises(Abort):
        windows.launch_app("notepad & calc")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows adapter")
def test_hotkey_rejects_unknown_combo(monkeypatch):
    from typesafe_computer_use import windows
    from typesafe_computer_use.models import Abort

    monkeypatch.setattr(windows, "_guard", lambda: None)
    with pytest.raises(Abort, match="unknown hotkey"):
        windows.hotkey("ctrl+alt+delete")
