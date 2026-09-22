"""One `Capability` type for everything Jarvis can do, with a risk level, so Jev questions and policy share a catalog.

The registry generates the same criteria dicts `agent.py` hands to Jev today; it does not replace them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

from typesafe_computer_use import config

from . import system


class Risk(IntEnum):
    READ = 0  # observes or informs; never changes the machine
    LOW = 1  # reversible with one more action: open, switch, volume
    MEDIUM = 2  # changes data or state; ask when the person is not the one who asked
    HIGH = 3  # cannot be taken back: send, pay, delete, close unsaved


@dataclass(frozen=True)
class Capability:
    id: str
    description: str
    risk: Risk
    gui: bool = False  # needs the foreground; gated on user presence
    device: str = "local"
    fn: Callable[..., object] | None = None
    available: bool = True

    @property
    def group(self) -> str:
        return self.id.split(".", 1)[0]

    @property
    def arg(self) -> str | None:
        return self.id.split(".", 1)[1] if "." in self.id else None


class Registry:
    def __init__(self, capabilities: list[Capability] | None = None):
        self._caps: dict[str, Capability] = {}
        for cap in capabilities or []:
            self.add(cap)

    def add(self, cap: Capability) -> Capability:
        self._caps[cap.id] = cap
        return cap

    def get(self, id: str) -> Capability | None:
        return self._caps.get(id)

    def __iter__(self):
        return iter(self._caps.values())

    def __len__(self) -> int:
        return len(self._caps)

    def group(self, name: str) -> list[Capability]:
        return [c for c in self._caps.values() if c.group == name]

    def criteria(self, group: str | None = None, max_risk: Risk | None = None, gui: bool | None = None) -> dict[str, str]:
        """`id -> description` for a Jev Choice; the key is the bare argument when a group is given."""
        out: dict[str, str] = {}
        for cap in self._caps.values():
            if not cap.available:
                continue
            if group is not None and cap.group != group:
                continue
            if max_risk is not None and cap.risk > max_risk:
                continue
            if gui is not None and cap.gui != gui:
                continue
            out[cap.arg or cap.id if group is not None else cap.id] = cap.description
        return out


def default_registry(speak: Callable[[str], None] | None = None) -> Registry:
    """The Windows PC's capabilities, described the way agent.py already describes them to Jev."""
    reg = Registry()
    reg.add(Capability("nothing", "Take no action.", Risk.READ))
    reg.add(Capability("notify.speak", "Say a short sentence out loud to the person.", Risk.READ, fn=speak))
    reg.add(Capability("notify.toast", "Show a desktop notification.", Risk.READ))
    for key, description in system.COMMANDS.items():
        risk = Risk.MEDIUM if key == "lock" else Risk.LOW
        reg.add(Capability(f"system.{key}", description, risk, fn=lambda command=key: system.run(command)))
    for key, spec in config.APPS.items():
        reg.add(Capability(f"open_app.{key}", f"Launch {spec['title'] or key} ({spec['exe']}).", Risk.LOW, gui=True))
    reg.add(Capability("switch_window", "Bring an already open window to the front.", Risk.LOW, gui=True))
    reg.add(
        Capability(
            "computer_use.goal",
            "Carry out a task on screen with the perception and action loop; each step is gated on its own.",
            Risk.LOW,
            gui=True,
        )
    )
    return reg
