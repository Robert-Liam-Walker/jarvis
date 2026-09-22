"""The world model: one entity per thing Jarvis tracks, rebuilt from events and re-verified on start.

`apply` is a pure reducer per event kind. The in-memory dict is mirrored to the store's `entities`
table so a restart begins from the last known state, and `reconcile` then re-asserts what is actually
present, emitting the started and stopped events that were missed while the daemon was down.
"""

from __future__ import annotations

import time
from typing import Any

from .events import Bus, Event
from .store import Store

Key = tuple[str, str]


class World:
    def __init__(self, store: Store | None = None):
        self.store = store
        self.entities: dict[Key, dict[str, Any]] = {}
        if store is not None:
            for row in store.entities():
                self.entities[(row["kind"], row["id"])] = row["state"]

    # queries

    def get(self, kind: str, id: str) -> dict[str, Any] | None:
        return self.entities.get((kind, id))

    def of_kind(self, kind: str) -> dict[str, dict[str, Any]]:
        return {k[1]: v for k, v in self.entities.items() if k[0] == kind}

    @property
    def user_active(self) -> bool | None:
        user = self.get("user", "local")
        if user is None:
            return None
        return user.get("presence") == "active"

    def snapshot(self) -> dict[str, Any]:
        """A compact picture for Jev state dicts and for `jarvis status`."""
        processes = self.of_kind("process")
        names = sorted({p.get("name", "?") for p in processes.values()})
        return {
            "user": self.get("user", "local") or {"presence": "unknown"},
            "foreground": self.get("window", "foreground"),
            "processes": {"count": len(processes), "names": names},
            "jupyter": self.of_kind("jupyter.kernel") or None,
        }

    # reducer

    def apply(self, event: Event) -> bool:
        """Fold one event in. Returns True when an entity changed."""
        reducer = getattr(self, f"_on_{event.kind.replace('.', '_')}", None)
        if reducer is None:
            return False
        return bool(reducer(event))

    def _set(self, kind: str, id: str, state: dict[str, Any], ts: float) -> bool:
        key = (kind, id)
        if self.entities.get(key) == state:
            if self.store is not None:
                self.store.upsert_entity(kind, id, state, ts)
            return False
        self.entities[key] = state
        if self.store is not None:
            self.store.upsert_entity(kind, id, state, ts)
        return True

    def _drop(self, kind: str, id: str) -> bool:
        existed = self.entities.pop((kind, id), None) is not None
        if self.store is not None:
            self.store.delete_entity(kind, id)
        return existed

    def _on_process_started(self, e: Event) -> bool:
        state = {"pid": int(e.key), "name": e.payload.get("name"), "exe": e.payload.get("exe"), "since": e.ts}
        return self._set("process", e.key, state, e.ts)

    def _on_process_stopped(self, e: Event) -> bool:
        return self._drop("process", e.key)

    def _on_user_idle(self, e: Event) -> bool:
        return self._set(
            "user", "local", {"presence": "idle", "since": e.ts, "idle_seconds": e.payload.get("idle_seconds")}, e.ts
        )

    def _on_user_active(self, e: Event) -> bool:
        return self._set("user", "local", {"presence": "active", "since": e.ts}, e.ts)

    def _on_window_focused(self, e: Event) -> bool:
        state = {
            "handle": e.key,
            "title": e.payload.get("title"),
            "exe": e.payload.get("exe"),
            "pid": e.payload.get("pid"),
            "since": e.ts,
        }
        return self._set("window", "foreground", state, e.ts)

    def _on_jupyter_kernel_busy(self, e: Event) -> bool:
        return self._set("jupyter.kernel", e.key, {**e.payload, "status": "busy", "since": e.ts}, e.ts)

    def _on_jupyter_kernel_idle(self, e: Event) -> bool:
        return self._set("jupyter.kernel", e.key, {**e.payload, "status": "idle", "since": e.ts}, e.ts)

    def _on_jupyter_kernel_died(self, e: Event) -> bool:
        return self._drop("jupyter.kernel", e.key)

    # reconcile

    def reconcile(self, bus: Bus, processes: dict[int, dict[str, Any]], now: float | None = None) -> tuple[int, int]:
        """Compare remembered processes with the live table. Emits what was missed. Returns (started, stopped)."""
        now = now or time.time()
        known = self.of_kind("process")
        started = stopped = 0
        for pid, info in processes.items():
            remembered = known.get(str(pid))
            if remembered is None or remembered.get("name") != info.get("name"):
                bus.publish(
                    Event(
                        "process.started",
                        str(pid),
                        "reconcile",
                        {"name": info.get("name"), "exe": info.get("exe"), "create_time": info.get("create_time")},
                        ts=now,
                        dedupe_key=f"process.started:{pid}:{info.get('create_time')}",
                    )
                )
                started += 1
        for pid_text, remembered in known.items():
            if int(pid_text) not in processes:
                bus.publish(
                    Event(
                        "process.stopped",
                        pid_text,
                        "reconcile",
                        {"name": remembered.get("name"), "exe": remembered.get("exe"), "missed": True},
                        ts=now,
                        dedupe_key=f"process.stopped:{pid_text}:{remembered.get('since')}",
                    )
                )
                stopped += 1
        return started, stopped
