"""One `authorize()` that every capability call passes through: allow, ask, or deny.

READ and LOW go through; MEDIUM and HIGH ask; anything unavailable is denied. GUI capabilities are
denied while the person is at the keyboard unless the request came from them (`foreground_ok`), which
is the default that keeps an autonomous agent from typing over someone's work. The per-step Gate the
runner already uses is the GUI adapter for this: it escalates a LOW step to HIGH when Jev judges it
destructive.
"""

from __future__ import annotations

from dataclasses import dataclass

from .capabilities import Capability, Risk
from .gates import Confirmer, Gate

ALLOW, ASK, DENY = "allow", "ask", "deny"


@dataclass(frozen=True)
class Context:
    user_active: bool | None = None  # None when presence is unknown, treated as active
    foreground_ok: bool = False  # the person asked for this just now, or the task was created for foreground use
    device: str = "local"


@dataclass(frozen=True)
class Verdict:
    decision: str
    reason: str

    def __bool__(self) -> bool:
        return self.decision == ALLOW


def authorize(cap: Capability, args: dict | None = None, ctx: Context | None = None) -> Verdict:
    ctx = ctx or Context()
    if not cap.available:
        return Verdict(DENY, f"{cap.id} is not available")
    if cap.device != ctx.device:
        return Verdict(DENY, f"{cap.id} belongs to device {cap.device!r}, not {ctx.device!r}")
    if cap.gui and ctx.user_active is not False and not ctx.foreground_ok:
        return Verdict(DENY, "the person is at the keyboard; GUI actions are notify-only until they are idle or ask")
    if cap.risk <= Risk.LOW:
        return Verdict(ALLOW, f"{cap.risk.name.lower()} risk")
    return Verdict(ASK, f"{cap.risk.name.lower()} risk needs a yes")


def step_gate(client, confirmer: Confirmer) -> Gate:
    """The runner's per-step gate, sourced from policy so the agent has one place to get it."""
    return Gate(client, confirmer)
