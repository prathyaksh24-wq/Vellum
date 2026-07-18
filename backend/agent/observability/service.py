"""Durable run metadata and a lightweight live-event fan-out.

Only operational metadata is stored here. Prompt text, response text, tool
arguments, source contents, and local paths are deliberately excluded.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs (
  response_id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  event_count INTEGER NOT NULL DEFAULT 0,
  tool_count INTEGER NOT NULL DEFAULT 0,
  source_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_observability_runs_started ON runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_observability_runs_thread ON runs(thread_id, started_at DESC);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  response_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  event_type TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'in_progress'
);
CREATE INDEX IF NOT EXISTS idx_observability_events_run ON events(response_id, id);
PRAGMA user_version = 1;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_text(value: Any, limit: int) -> str:
    """Keep labels useful without allowing content-shaped payloads to persist."""

    text = " ".join(str(value or "").split())
    return text[:limit]


class ObservabilityService:
    """Capture sanitized response lifecycle events and stream them to the UI."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        return conn

    def capture(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Persist a safe projection of one response event and publish it live."""

        event_type = str(payload.get("type") or "")
        response_id = _safe_text(payload.get("response_id"), 96)
        thread_id = _safe_text(payload.get("thread_id"), 128)
        if not response_id or not thread_id:
            return None

        ts = _safe_text(payload.get("created_at"), 40) or _now()
        public_type = ""
        label = ""
        name = ""
        status = "in_progress"
        tool_count = 0
        source_count = 0

        if event_type == "response.created":
            public_type = "run_started"
            label = "Run started"
        elif event_type == "agent.activity":
            activity = payload.get("activity") if isinstance(payload.get("activity"), dict) else {}
            public_type = _safe_text(activity.get("type"), 64) or "activity"
            label = _safe_text(activity.get("label"), 160)
            name = _safe_text(activity.get("name"), 96)
            status = _safe_text(activity.get("status"), 32) or "in_progress"
        elif event_type == "response.completed":
            response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
            public_type = "run_completed"
            label = "Run completed"
            status = "completed"
            tool_count = len(response.get("tools") or [])
            source_count = len(response.get("sources") or [])
        elif event_type == "error":
            public_type = "run_failed"
            label = "Run failed"
            status = "failed"
        else:
            return None

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(response_id, thread_id, status, started_at)
                VALUES (?, ?, 'in_progress', ?)
                ON CONFLICT(response_id) DO NOTHING
                """,
                (response_id, thread_id, ts),
            )
            cur = conn.execute(
                """
                INSERT INTO events(response_id, thread_id, ts, event_type, label, name, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (response_id, thread_id, ts, public_type, label, name, status),
            )
            if public_type == "run_completed":
                conn.execute(
                    """
                    UPDATE runs SET status='completed', completed_at=?,
                      event_count=event_count+1, tool_count=?, source_count=?
                    WHERE response_id=?
                    """,
                    (ts, tool_count, source_count, response_id),
                )
            elif public_type == "run_failed":
                conn.execute(
                    "UPDATE runs SET status='failed', completed_at=?, event_count=event_count+1 WHERE response_id=?",
                    (ts, response_id),
                )
            else:
                conn.execute(
                    "UPDATE runs SET event_count=event_count+1 WHERE response_id=?",
                    (response_id,),
                )
            event_id = int(cur.lastrowid)

        event = {
            "id": event_id,
            "response_id": response_id,
            "thread_id": thread_id,
            "ts": ts,
            "type": public_type,
            "label": label,
            "name": name,
            "status": status,
        }
        self._publish(event)
        return event

    def _publish(self, event: dict[str, Any]) -> None:
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self._subscribers.discard(queue)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def events_since(self, event_id: int, *, limit: int = 250) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, response_id, thread_id, ts, event_type AS type, label, name, status "
                "FROM events WHERE id > ? ORDER BY id LIMIT ?",
                (max(0, int(event_id)), max(1, min(int(limit), 1000))),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_runs(self, *, limit: int = 12) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self, *, days: int | None = 7) -> dict[str, Any]:
        cutoff = None if days is None else (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        where = "" if cutoff is None else "WHERE started_at >= ?"
        params: tuple[Any, ...] = () if cutoff is None else (cutoff,)
        with self._connect() as conn:
            totals = conn.execute(
                f"""
                SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                  SUM(CASE WHEN status='in_progress' THEN 1 ELSE 0 END) AS active
                FROM runs {where}
                """,
                params,
            ).fetchone()
            active = conn.execute(
                "SELECT * FROM runs WHERE status='in_progress' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        result = {key: int(totals[key] or 0) for key in ("total", "completed", "failed", "active")}
        result["success_rate"] = result["completed"] / max(result["completed"] + result["failed"], 1)
        result["active_run"] = dict(active) if active else None
        return result

    def raw_event_rows(self) -> list[dict[str, Any]]:
        """Test/support helper; never exposed by the API."""

        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
        return [dict(row) for row in rows]
