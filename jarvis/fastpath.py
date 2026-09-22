"""The first Jev call after an utterance: what kind of request is this, and which app, window, or command?

Code proposes the candidates (from the utterance, the app catalog, the open windows); Jev picks. The goal
path only starts when Jev says the utterance needs the screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from typesafe_sdk import Choice, TypeSafeClient

from typesafe_computer_use import config

from . import extract, system

KINDS: dict[str, str] = {
    "open_app": "Launch an application, then possibly continue with a task inside it.",
    "switch_window": "Bring an already open window to the front.",
    "system": "A system-level command that needs no screen: volume, media playback, lock, screenshot.",
    "goal": "A task to carry out on screen in the current or named application: click, type, navigate.",
    "cancel": "Stop what is happening, or the utterance was not a request (small talk, noise, a fragment).",
}


@dataclass(frozen=True)
class Intent:
    kind: str
    confidence: float
    app: str | None = None
    window: str | None = None
    command: str | None = None
    remainder: str = ""
    probabilities: dict[str, float] = field(default_factory=dict)


def decide(client: TypeSafeClient, utterance: str, open_windows: list[str]) -> Intent:
    app_name, remainder = extract.split_open_app(utterance)
    switch = extract.switch_target(utterance)
    app_keys = extract.app_candidates(app_name or switch or "", config.APPS) or list(config.APPS)
    windows = [w for w in open_windows if not switch or switch in w.lower()] or open_windows

    questions: dict = {
        "kind": Choice(
            instructions=(
                "A person just spoke this to their computer assistant. Which kind of request is it? "
                "'open_app' only when a program must be launched; 'switch_window' when an already open "
                "window is named; 'system' for volume, media, lock, or screenshot; 'goal' for anything "
                "that must be done on screen; 'cancel' for stop words, small talk, or noise."
            ),
            criteria=KINDS,
        ),
        "app": Choice(
            instructions="If an application is to be launched, which one? 'none' if no launch is needed.",
            criteria={
                **{k: f"{k} ({config.APPS[k]['title'] or config.APPS[k]['exe']})" for k in app_keys},
                "none": "No application.",
            },
        ),
        "command": Choice(
            instructions="If this is a system command, which one? 'none' otherwise.",
            criteria={**system.COMMANDS, "none": "Not a system command."},
        ),
    }
    if windows:
        questions["window"] = Choice(
            instructions="If an already open window is to be brought forward, which one? 'none' otherwise.",
            criteria={**{w: f"the window titled {w!r}" for w in windows[:60]}, "none": "No window switch."},
        )
    state = {
        "utterance": utterance,
        "parsed": {"app_named": app_name, "switch_named": switch, "task_after_app": remainder if app_name else None},
        "open_windows": open_windows[:60],
    }
    answers = client.system_one(state=state, questions=questions).answers
    kind = answers["kind"]
    app = answers["app"].choice if answers["app"].choice != "none" else None
    window = answers["window"].choice if "window" in answers and answers["window"].choice != "none" else None
    command = answers["command"].choice if answers["command"].choice != "none" else None
    confidence = kind.confidence
    if kind.choice == "open_app" and app:
        confidence = min(confidence, answers["app"].confidence)
    if kind.choice == "switch_window" and window:
        confidence = min(confidence, answers["window"].confidence)
    if kind.choice == "system" and command:
        confidence = min(confidence, answers["command"].confidence)
    return Intent(
        kind=kind.choice,
        confidence=confidence,
        app=app,
        window=window,
        command=command,
        remainder=remainder if app_name else utterance.strip(),
        probabilities=dict(kind.probabilities),
    )
