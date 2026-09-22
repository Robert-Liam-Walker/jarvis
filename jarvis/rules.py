"""Standing rules the person configures: which processes to watch, when they count as idle, how many Jev calls a minute.

Lives in a user file under the Jarvis home, not in the repo, so the repository stays generic.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .store import home

DEFAULT_WATCH = ["notepad.exe", "python.exe", "jupyter.exe", "code.exe"]


@dataclass
class Rules:
    watch_processes: list[str] = field(default_factory=lambda: list(DEFAULT_WATCH))
    idle_after: float = 120.0
    jev_calls_per_minute: int = 20
    debounce_seconds: float = 5.0
    toasts: bool = True

    def watches(self, name: str | None) -> bool:
        if not name:
            return False
        lowered = name.lower()
        return any(lowered == w.lower() or lowered == w.lower() + ".exe" for w in self.watch_processes)


def path() -> Path:
    return home() / "config.json"


def load(file: Path | None = None) -> Rules:
    """Read the rules file, writing the defaults first if it does not exist yet."""
    file = file or path()
    rules = Rules()
    if not file.exists():
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(asdict(rules), indent=2) + "\n", encoding="utf-8")
        return rules
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"jarvis: could not read {file}: {e}; using defaults", flush=True)
        return rules
    for name in asdict(rules):
        if name in data:
            setattr(rules, name, data[name])
    return rules
