from dataclasses import dataclass, field

from jarvis import fastpath


@dataclass
class FakeChoice:
    choice: str
    confidence: float = 0.9
    probabilities: dict = field(default_factory=dict)


class FakeAnswers:
    def __init__(self, answers):
        self.answers = answers


class ScriptedClient:
    """Answers each question by name from a script; records the request."""

    def __init__(self, script: dict[str, str], confidence: float = 0.9):
        self.script = script
        self.confidence = confidence
        self.requests = []

    def system_one(self, state, questions):
        self.requests.append((state, questions))
        return FakeAnswers({name: FakeChoice(self.script.get(name, "none"), self.confidence) for name in questions})


def test_open_app_with_remainder_becomes_goal_text():
    client = ScriptedClient({"kind": "open_app", "app": "notepad"})
    intent = fastpath.decide(client, "open notepad and write hello", ["Calculator"])
    assert intent.kind == "open_app" and intent.app == "notepad" and intent.remainder == "write hello"
    state, questions = client.requests[0]
    assert state["parsed"]["app_named"] == "notepad"
    assert list(questions["app"].criteria)[:1] == ["notepad"]  # the parsed name is offered first
    assert "none" in questions["app"].criteria


def test_switch_window_offers_matching_titles_first():
    client = ScriptedClient({"kind": "switch_window", "window": "Calculator"})
    intent = fastpath.decide(client, "switch back to calculator", ["Untitled - Notepad", "Calculator"])
    assert intent.kind == "switch_window" and intent.window == "Calculator"
    assert next(iter(client.requests[0][1]["window"].criteria)) == "Calculator"


def test_system_command_and_confidence_floor():
    client = ScriptedClient({"kind": "system", "command": "volume_up"}, confidence=0.3)
    intent = fastpath.decide(client, "turn it up", [])
    assert intent.kind == "system" and intent.command == "volume_up"
    assert intent.confidence == 0.3


def test_goal_keeps_whole_utterance():
    client = ScriptedClient({"kind": "goal"})
    intent = fastpath.decide(client, "save this file", ["Untitled - Notepad"])
    assert intent.kind == "goal" and intent.remainder == "save this file" and intent.app is None


def test_no_windows_means_no_window_question():
    client = ScriptedClient({"kind": "cancel"})
    fastpath.decide(client, "never mind", [])
    assert "window" not in client.requests[0][1]
