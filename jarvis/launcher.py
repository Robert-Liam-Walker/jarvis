"""Launch and switch applications. Deterministic; Jev only names the app."""

from __future__ import annotations

import time
from dataclasses import dataclass

from typesafe_computer_use import config, macos
from typesafe_computer_use.models import Abort


@dataclass(frozen=True)
class Launched:
    app: str
    title: str
    handle: int
    seconds: float


def open_app(app: str, timeout: float = 8.0) -> Launched:
    """Start (or focus) a catalog app and make its window the observed foreground window."""
    spec = config.APPS.get(app)
    if spec is None:
        raise Abort(f"unknown app {app!r}")
    started = time.perf_counter()
    existing = None if spec.get("fresh") else macos.find_window(spec["title"] or None, spec["exe"])
    if existing is None:
        before = {w["handle"] for w in macos.list_windows()}
        macos.launch_app(spec["launch"])
        existing = macos.wait_for_window(spec["title"] or None, spec["exe"], timeout, exclude_handles=before)
        if existing is None:
            raise Abort(f"{app} did not open a window within {timeout:.0f}s")
        time.sleep(0.3)  # let the new window finish its first layout before UIA reads it
    if not macos.activate_handle(existing["handle"]):
        raise Abort(f"could not bring {app} to the front")
    return Launched(app, existing["title"], existing["handle"], round(time.perf_counter() - started, 2))


def switch_to(title_fragment: str) -> str:
    """Bring the one visible window whose title contains the fragment forward."""
    matches = [w for w in macos.list_windows() if title_fragment.lower() in w["title"].lower()]
    if not matches:
        raise Abort(f"no open window matches {title_fragment!r}")
    if not macos.activate_handle(matches[0]["handle"]):
        raise Abort(f"could not activate {matches[0]['title']!r}")
    return matches[0]["title"]


def open_windows() -> list[str]:
    return [w["title"] for w in macos.list_windows()]
