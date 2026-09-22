"""The one file that survives a restart: events, entities, tasks, decisions, runs and approvals in SQLite.

Stdlib only, WAL mode, one writer lock. Every event insert is idempotent on its dedupe key, so an
observer that reconnects and replays is a no-op. `JARVIS_HOME` overrides the directory for tests.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .events import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS events_kind_ts ON events (kind, ts);
CREATE TABLE IF NOT EXISTS entities (
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    updated_ts REAL NOT NULL,
    seen_ts REAL NOT NULL,
    stale INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    deadline REAL,
    constraints_json TEXT NOT NULL DEFAULT '{}',
    plan_json TEXT NOT NULL DEFAULT '[]',
    attempts INTEGER NOT NULL DEFAULT 0,
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    subscriptions_json TEXT NOT NULL DEFAULT '[]',
    last_event_id INTEGER,
    created_ts REAL NOT NULL,
    updated_ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    event_id INTEGER,
    task_id INTEGER,
    question TEXT NOT NULL,
    answer_json TEXT NOT NULL,
    probabilities_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    folder TEXT NOT NULL,
    outcome TEXT,
    started_ts REAL NOT NULL,
    ended_ts REAL
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    question TEXT NOT NULL,
    asked_ts REAL NOT NULL,
    answered_ts REAL,
    answer TEXT
);
"""

TASK_STATUSES = ("pending", "active", "waiting_event", "waiting_approval", "waiting_host", "done", "failed", "cancelled")


def home() -> Path:
    """Where Jarvis keeps its state: `JARVIS_HOME`, else %LOCALAPPDATA%/jarvis, else ~/.jarvis."""
    override = os.environ.get("JARVIS_HOME")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "jarvis" if local else Path.home() / ".jarvis"


def _row(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    out = {desc[0]: value for desc, value in zip(cursor.description, row, strict=True)}
    for name in list(out):
        if name.endswith("_json"):
            out[name[: -len("_json")]] = json.loads(out.pop(name))
    return out


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or home() / "jarvis.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # events

    def append_event(self, event: Event) -> int | None:
        """Insert one event. Returns its id, or None when the dedupe key was already stored."""
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO events (ts, source, kind, key, payload_json, dedupe_key) VALUES (?, ?, ?, ?, ?, ?)",
                (event.ts, event.source, event.kind, event.key, json.dumps(event.payload, default=str), event.dedupe_key),
            )
            return cur.lastrowid if cur.rowcount == 1 else None

    def recent_events(self, limit: int = 50, kind: str | None = None, since_id: int = 0) -> list[dict[str, Any]]:
        sql = "SELECT * FROM events WHERE id > ?"
        args: list[Any] = [since_id]
        if kind:
            sql += " AND kind LIKE ?"
            args.append(kind.replace("*", "%"))
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            cur = self._db.execute(sql, args)
            return [_row(cur, r) for r in cur.fetchall()]

    def prune_events(self, older_than_days: float = 7.0) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM events WHERE ts < ?", (time.time() - older_than_days * 86400,))
            return cur.rowcount

    # entities

    def upsert_entity(self, kind: str, id: str, state: dict, ts: float | None = None, stale: bool = False) -> None:
        ts = ts or time.time()
        with self._lock:
            self._db.execute(
                "INSERT INTO entities (kind, id, state_json, updated_ts, seen_ts, stale) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(kind, id) DO UPDATE SET state_json=excluded.state_json, updated_ts=excluded.updated_ts, "
                "seen_ts=excluded.seen_ts, stale=excluded.stale",
                (kind, id, json.dumps(state, default=str), ts, ts, int(stale)),
            )

    def delete_entity(self, kind: str, id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM entities WHERE kind = ? AND id = ?", (kind, id))

    def entities(self, kind: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM entities", []
        if kind:
            sql += " WHERE kind = ?"
            args.append(kind)
        with self._lock:
            cur = self._db.execute(sql + " ORDER BY kind, id", args)
            return [_row(cur, r) for r in cur.fetchall()]

    def mark_stale(self, kind: str, ts: float | None = None) -> None:
        """Flag every entity of a kind as unverified; reconcile then re-asserts the ones still present."""
        with self._lock:
            self._db.execute("UPDATE entities SET stale = 1 WHERE kind = ?", (kind,))

    # tasks

    def create_task(self, goal: str, priority: int = 0, deadline: float | None = None, **fields) -> int:
        now = time.time()
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO tasks (goal, status, priority, deadline, constraints_json, plan_json, capabilities_json, "
                "subscriptions_json, created_ts, updated_ts) VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    goal,
                    priority,
                    deadline,
                    json.dumps(fields.get("constraints", {})),
                    json.dumps(fields.get("plan", [])),
                    json.dumps(fields.get("capabilities", [])),
                    json.dumps(fields.get("subscriptions", [])),
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def update_task(self, task_id: int, **fields) -> None:
        if "status" in fields and fields["status"] not in TASK_STATUSES:
            raise ValueError(f"unknown task status {fields['status']!r}")
        sets, args = ["updated_ts = ?"], [time.time()]
        for name, value in fields.items():
            if name in ("constraints", "plan", "capabilities", "subscriptions"):
                sets.append(f"{name}_json = ?")
                args.append(json.dumps(value))
            else:
                sets.append(f"{name} = ?")
                args.append(value)
        args.append(task_id)
        with self._lock:
            self._db.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", args)

    def tasks(self, status: str | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM tasks", []
        if status:
            statuses = (status,) if isinstance(status, str) else status
            sql += f" WHERE status IN ({','.join('?' * len(statuses))})"
            args.extend(statuses)
        with self._lock:
            cur = self._db.execute(sql + " ORDER BY priority DESC, id", args)
            return [_row(cur, r) for r in cur.fetchall()]

    def demote_interrupted_tasks(self) -> int:
        """On start, whatever was `active` was interrupted: back to pending with one more attempt counted."""
        with self._lock:
            cur = self._db.execute(
                "UPDATE tasks SET status = 'pending', attempts = attempts + 1, updated_ts = ? WHERE status = 'active'",
                (time.time(),),
            )
            return cur.rowcount

    # decisions, runs, approvals

    def record_decision(
        self,
        question: str,
        answer: dict,
        probabilities: dict | None = None,
        event_id: int | None = None,
        task_id: int | None = None,
    ) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO decisions (ts, event_id, task_id, question, answer_json, probabilities_json) VALUES (?, ?, ?, ?, ?, ?)",
                (time.time(), event_id, task_id, question, json.dumps(answer, default=str), json.dumps(probabilities or {})),
            )
            return int(cur.lastrowid)

    def recent_decisions(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._db.execute("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,))
            return [_row(cur, r) for r in cur.fetchall()]

    def start_run(self, folder: str, task_id: int | None = None) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO runs (task_id, folder, started_ts) VALUES (?, ?, ?)", (task_id, folder, time.time())
            )
            return int(cur.lastrowid)

    def end_run(self, run_id: int, outcome: str) -> None:
        with self._lock:
            self._db.execute("UPDATE runs SET outcome = ?, ended_ts = ? WHERE id = ?", (outcome, time.time(), run_id))

    def ask_approval(self, question: str, task_id: int | None = None) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO approvals (task_id, question, asked_ts) VALUES (?, ?, ?)", (task_id, question, time.time())
            )
            return int(cur.lastrowid)

    def answer_approval(self, approval_id: int, answer: str) -> None:
        with self._lock:
            self._db.execute("UPDATE approvals SET answer = ?, answered_ts = ? WHERE id = ?", (answer, time.time(), approval_id))
