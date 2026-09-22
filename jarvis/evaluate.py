"""Jev looks at an event: is it relevant, what if anything to do about it, and should the person be told?

Code filters first (the agent's own effects, debounce, kinds nobody watches), then one `system_one`
call with three questions, then policy. Every answer is written to the decisions table. Without a
Jev client the standing rules alone decide, so the notify path can be exercised before a key exists.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from typesafe_sdk import Choice, Noul

from . import policy
from .capabilities import Registry, Risk
from .events import Debouncer, Event, TokenBucket
from .notify import Notifier
from .rules import Rules
from .store import Store
from .world import World

ACT_ABOVE = 0.5
INTERESTING = ("process.started", "process.stopped", "jupyter.kernel.idle", "jupyter.kernel.died", "window.focused")


@dataclass(frozen=True)
class Verdict:
    relevant: float
    action: str
    action_confidence: float
    notify: float
    source: str  # "jev" or "rule"
    probabilities: dict[str, float] = field(default_factory=dict)

    @property
    def acts(self) -> bool:
        return self.relevant >= ACT_ABOVE and self.action != "nothing" and self.action_confidence >= ACT_ABOVE


def describe(event: Event) -> str:
    """The sentence the person hears. Plain, one line, names the thing."""
    name = event.payload.get("name") or event.payload.get("title") or event.key
    if event.kind == "process.stopped":
        return f"{name} has exited." if not event.payload.get("missed") else f"{name} exited while I was away."
    if event.kind == "process.started":
        return f"{name} has started."
    if event.kind == "jupyter.kernel.died":
        return f"The Jupyter kernel for {event.payload.get('path', name)} has died."
    if event.kind == "jupyter.kernel.idle":
        return f"The Jupyter kernel for {event.payload.get('path', name)} finished running."
    return f"{event.kind.replace('.', ' ')}: {name}."


class Evaluator:
    def __init__(
        self,
        registry: Registry,
        world: World,
        notifier: Notifier,
        rules: Rules | None = None,
        client=None,
        store: Store | None = None,
        own_source: str = "jarvis",
    ):
        self.registry = registry
        self.world = world
        self.notifier = notifier
        self.rules = rules or Rules()
        self.client = client
        self.store = store
        self.own_source = own_source
        self.debounce = Debouncer(self.rules.debounce_seconds)
        self.budget = TokenBucket(self.rules.jev_calls_per_minute)
        self.skipped = 0
        self.verdicts: list[tuple[Event, Verdict]] = []

    # code filters

    def wants(self, event: Event) -> bool:
        if event.source == self.own_source:
            return False
        if event.kind not in INTERESTING:
            return False
        if event.kind.startswith("process.") and not self.rules.watches(event.payload.get("name")):
            return False
        if event.kind == "process.started" and event.source == "reconcile":
            return False  # catch-up after a restart: it was already running, nothing happened just now
        if event.kind == "window.focused":
            return False  # tracked in the world; nobody subscribes yet
        return self.debounce.allow(f"{event.kind}:{event.name}")

    # the Jev question

    def evaluate(self, event: Event) -> Verdict | None:
        if not self.wants(event):
            return None
        if self.client is None:
            verdict = Verdict(1.0, "notify.speak", 1.0, 1.0, "rule")
        elif not self.budget.take():
            self.skipped += 1
            return None
        else:
            verdict = self._ask(event)
        if self.store is not None:
            self.store.record_decision(
                "evaluate",
                {"relevant": verdict.relevant, "action": verdict.action, "notify": verdict.notify, "source": verdict.source},
                verdict.probabilities,
                event_id=event.id,
            )
        self.verdicts.append((event, verdict))
        return verdict

    def _ask(self, event: Event) -> Verdict:
        candidates = self.registry.criteria(max_risk=Risk.READ, gui=False)
        state = {
            "event": {
                "kind": event.kind,
                "about": event.name,
                "payload": event.payload,
                "age_seconds": round(time.time() - event.ts, 1),
            },
            "watched_processes": self.rules.watch_processes,
            "world": self.world.snapshot(),
            "open_tasks": [t["goal"] for t in (self.store.tasks(("pending", "active", "waiting_event")) if self.store else [])][
                :10
            ],
        }
        questions = {
            "relevant": Noul(
                instructions=(
                    "Is this event something the person would want their assistant to act on or mention: "
                    "a watched program or job ending, failing, or finishing, rather than routine background churn?"
                )
            ),
            "action": Choice(
                instructions="What should the assistant do about it right now? 'nothing' when it is not worth acting on.",
                criteria=candidates,
            ),
            "notify": Noul(instructions="Should the person be told about this now, in one spoken sentence?"),
        }
        answers = self.client.system_one(state=state, questions=questions).answers
        action = answers["action"]
        return Verdict(
            relevant=float(answers["relevant"].noul),
            action=action.choice,
            action_confidence=float(action.confidence),
            notify=float(answers["notify"].noul),
            source="jev",
            probabilities=dict(getattr(action, "probabilities", {}) or {}),
        )

    # act

    def handle(self, event: Event) -> Verdict | None:
        """Bus subscriber: evaluate, authorize, and carry out a READ-level action."""
        verdict = self.evaluate(event)
        if verdict is None or not verdict.acts:
            return verdict
        cap = self.registry.get(verdict.action)
        if cap is None:
            return verdict
        ok = policy.authorize(cap, ctx=policy.Context(user_active=self.world.user_active))
        if not ok:
            print(f"jarvis: {cap.id} denied: {ok.reason}", flush=True)
            return verdict
        if cap.id == "notify.speak" or cap.id == "notify.toast":
            self.notifier.notify(describe(event))
        elif cap.fn is not None:
            cap.fn()
        return verdict
