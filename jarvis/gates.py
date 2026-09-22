"""Before an action lands: is it the kind that cannot be taken back? If so, ask the person first.

Code decides which actions are even worth asking about (a click on 'Cancel' never is); Jev judges
whether this particular action, on this screen, toward this goal, is destructive; the person confirms.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable

from typesafe_sdk import Noul, TypeSafeClient

from typesafe_computer_use.decide import Decision
from typesafe_computer_use.models import Item, Screen

ALWAYS_ASK_HOTKEYS = {"alt+f4", "ctrl+w"}
RISKY_WORDS = re.compile(
    r"\b(delete|remove|erase|discard|send|submit|pay|purchase|buy|order|confirm|apply|reset|format|uninstall|"
    r"sign out|log out|shut ?down|restart|close|don'?t save|do not save|empty|clear all|unsubscribe|transfer|wipe)\b",
    re.IGNORECASE,
)
ASK_ABOVE = 0.5
YES = re.compile(r"^\W*(yes|yeah|yep|yup|confirm|do it|go ahead|sure|okay|ok)\b", re.IGNORECASE)


def looks_risky(decision: Decision, items: list[Item]) -> str | None:
    """A one-line description of the action when it is worth a Jev judgement, else None."""
    kind = decision.kind.choice
    if kind == "hotkey" and decision.hotkey and decision.hotkey.choice in ALWAYS_ASK_HOTKEYS:
        return f"press {decision.hotkey.choice}"
    if decision.clicking:
        by_index = {str(it.index): it for it in items}
        item = by_index.get(decision.item.choice)
        if item is not None and RISKY_WORDS.search(item.text):
            return f"click {item.text!r}"
    if kind == "press_offscreen" and decision.offscreen:
        return None
    if kind == "press_enter":
        nearby = " ".join(it.text for it in items[:120])
        if RISKY_WORDS.search(nearby):
            return "press Enter on a form that mentions a risky action"
    return None


class Confirmer:
    """Blocks the worker on a yes/no question; the answer arrives from a typed prompt or the next utterance."""

    def __init__(self, ask: Callable[[str], None], timeout: float = 20.0):
        self.ask = ask
        self.timeout = timeout
        self._answer: str | None = None
        self._event = threading.Event()
        self.pending: str | None = None

    def confirm(self, question: str) -> bool:
        self._answer = None
        self._event.clear()
        self.pending = question
        self.ask(question)
        try:
            if not self._event.wait(self.timeout):
                return False
            return bool(self._answer and YES.match(self._answer))
        finally:
            self.pending = None

    def answer(self, text: str) -> bool:
        """Deliver a reply. Returns True when a question was waiting for it."""
        if self.pending is None:
            return False
        self._answer = text
        self._event.set()
        return True


class Gate:
    def __init__(self, client: TypeSafeClient, confirmer: Confirmer, ask_above: float = ASK_ABOVE):
        self.client = client
        self.confirmer = confirmer
        self.ask_above = ask_above
        self.last_probability: float | None = None

    def __call__(self, decision: Decision, screen: Screen, items: list[Item], goal: str) -> bool:
        """True to let the action through."""
        description = looks_risky(decision, items)
        if description is None:
            return True
        state = {
            "goal": goal,
            "about_to": description,
            "frontmost_app": screen.app,
            "focused_field": screen.field.summary() if screen.field else None,
            "screen_text": [it.text for it in items][:80],
        }
        question = Noul(
            instructions=(
                "Would carrying out this action delete or discard data, send a message, make a payment, "
                "close unsaved work, or change account or security settings, in a way that cannot simply "
                "be undone with one more click?"
            )
        )
        probability = self.client.system_one(state=state, questions={"risky": question}).answers["risky"].noul
        self.last_probability = probability
        if probability < self.ask_above:
            return True
        return self.confirmer.confirm(f"This will {description}. Should I go ahead?")
