"""One resident agent: a single Jev client, an utterance in, the machine driven, a sentence back."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from typesafe_sdk import TypeSafeClient

from typesafe_computer_use import config, macos
from typesafe_computer_use.actions import Context
from typesafe_computer_use.models import Abort
from typesafe_computer_use.runner import STOPPED, RunConfig, run
from typesafe_computer_use.writer import make_writer

from . import extract, fastpath, launcher, stopkey, system
from .gates import Confirmer, Gate

Narrator = Callable[[str], None]
MIN_INTENT_CONFIDENCE = 0.45


@dataclass
class Result:
    utterance: str
    outcome: str
    said: str
    steps: int
    seconds: float


def app_criteria() -> dict[str, str]:
    return {key: f"Launch {spec['title'] or key} ({spec['exe']})." for key, spec in config.APPS.items()}


def window_criteria(exclude: str | None = None) -> dict[str, str]:
    titles = [t for t in launcher.open_windows() if t != exclude]
    return {t: f"Bring the window titled {t!r} to the front." for t in titles[:60]}


def hotkey_criteria() -> dict[str, str]:
    names = {
        "ctrl+s": "Save the current document.",
        "ctrl+z": "Undo the last edit.",
        "ctrl+y": "Redo.",
        "ctrl+f": "Open find.",
        "ctrl+a": "Select all.",
        "ctrl+n": "New document or window.",
        "ctrl+t": "New browser tab.",
        "ctrl+w": "Close the current tab or document.",
        "win+d": "Show the desktop.",
        "win+left": "Snap the window to the left half.",
        "win+right": "Snap the window to the right half.",
    }
    return {k: v for k, v in names.items() if k in getattr(macos, "HOTKEYS", {})}


class Agent:
    def __init__(
        self,
        client: TypeSafeClient,
        narrate: Narrator = print,
        runs_dir: Path | None = None,
        act: bool = True,
        confirmer: Confirmer | None = None,
    ):
        self.client = client
        self.narrate = narrate
        self.runs_dir = runs_dir or Path("runs")
        self.act = act
        self.writer = make_writer()
        self.confirmer = confirmer or Confirmer(ask=narrate)
        self.gate = Gate(client, self.confirmer)

    def say(self, utterance: str) -> Result:
        """Handle one utterance end to end: one Jev call to classify it, then the deterministic or screen path."""
        started = time.perf_counter()
        utterance = utterance.strip()
        if not utterance:
            return Result(utterance, "cancel", "", 0, 0.0)
        try:
            intent = fastpath.decide(self.client, utterance, launcher.open_windows())
            if intent.confidence < MIN_INTENT_CONFIDENCE and intent.kind != "goal":
                return self._finish(utterance, "unsure", "I'm not sure what you meant.", 0, started)
            if intent.kind == "cancel":
                return self._finish(utterance, "cancel", "Okay.", 0, started)
            if intent.kind == "system" and intent.command:
                return self._finish(utterance, "done", system.run(intent.command).capitalize() + ".", 1, started)
            if intent.kind == "switch_window" and intent.window:
                title = launcher.switch_to(intent.window)
                return self._finish(utterance, "done", f"Switched to {title}.", 1, started)
            window_title: str | None = None
            if intent.kind == "open_app" and intent.app:
                self.narrate(f"Opening {intent.app}.")
                window_title = launcher.open_app(intent.app).title
                if not intent.remainder:
                    return self._finish(utterance, "done", f"{intent.app} is open.", 1, started)
        except Abort as e:
            return self._finish(utterance, f"aborted ({e})", str(e), 0, started)
        goal = intent.remainder or utterance
        state = self._run_goal(goal, window_title)
        said = self._sentence(state.outcome, state.answer.text if state.answer else None)
        return self._finish(utterance, state.outcome, said, len(state.history), started)

    def _finish(self, utterance: str, outcome: str, said: str, steps: int, started: float) -> Result:
        if said:
            self.narrate(said)
        return Result(utterance, outcome, said, steps, round(time.perf_counter() - started, 2))

    def _run_goal(self, goal: str, window_title: str | None):
        out = self.runs_dir / time.strftime("%Y%m%d-%H%M%S")
        candidates = tuple(extract.text_candidates(goal))
        cfg = RunConfig(
            goal=goal,
            out=out,
            act=self.act,
            steps=int(os.environ.get("JARVIS_STEPS", "25")),
            min_confidence=config.DEFAULT_MIN_CONFIDENCE,
            delay=config.JARVIS_DELAY,
            window_title=window_title,
            on_event=self._on_event,
            gate=self.gate,
        )
        stopkey.clear_stop()

        def ctx_factory(typesafe, history):
            return Context(
                goal=goal,
                browser=config.browser(),
                email=config.email(),
                typesafe=typesafe,
                writer=self.writer,
                history=history,
                apps=app_criteria(),
                windows=window_criteria(exclude=window_title),
                hotkeys=hotkey_criteria(),
                text_candidates=candidates,
            )

        try:
            return run(cfg, ctx_factory, client=self.client)
        finally:
            stopkey.clear_stop()

    def _on_event(self, kind: str, payload: dict) -> None:
        if kind == "acted":
            self.narrate(payload["what"])

    @staticmethod
    def _sentence(outcome: str, answer: str | None) -> str:
        if answer:
            return answer
        if outcome == "done":
            return "Done."
        if outcome == "dry run":
            return "Dry run only; nothing was clicked."
        return f"Stopped: {STOPPED.get(outcome, outcome)}."


def make_client() -> TypeSafeClient:
    from typesafe_computer_use.credentials import prepare_provider

    config.load_dotenv(Path.cwd() / ".env")
    prepare_provider()
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise SystemExit("TYPESAFE_API_KEY is not set (export it, put it in .env, or use 1-Start.cmd > Change API key)")
    return TypeSafeClient(
        base_url=os.environ.get("TYPESAFE_BASE_URL"), model=os.environ.get("TYPESAFE_DEFAULT_MODEL"), timeout=20
    )
