from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sqlite3
import time
from typing import Any
import uuid

from agent.skills.privacy import SkillPrivacyGate


_CURRENT_SCOPE: ContextVar["SkillUsageScope | None"] = ContextVar("skill_usage_scope", default=None)


class SkillUsageIntelligence:
    OUTCOMES = {"completed", "failed", "corrected", "cancelled", "unknown"}

    def __init__(self, root: str | Path = ".skills", *, db_path: str | Path | None = None):
        root_path = Path(root)
        self.path = Path(db_path) if db_path else root_path.parent / "data" / "skills" / "usage.db"
        self.gate = SkillPrivacyGate()
        self._migrate()

    def activate(self, skill_name: str, *, task_summary: str, thread_id: str, source: str) -> str:
        clean = self.gate.sanitize(task_summary).text[:500]
        event_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO usage_events(id,skill_name,task_summary,thread_hash,source,outcome,tool_count,latency_ms,created_at) VALUES(?,?,?,?,?,'unknown',0,0,?)",
                (event_id, skill_name.casefold(), clean, hashlib.sha256(thread_id.encode("utf-8")).hexdigest(), source, datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()
        return event_id

    def finish(self, event_id: str, *, outcome: str, tool_count: int = 0, latency_ms: int = 0) -> None:
        normalized = outcome.casefold()
        if normalized not in self.OUTCOMES:
            raise ValueError(f"invalid skill usage outcome: {outcome}")
        with self._connect() as connection:
            row = connection.execute("SELECT skill_name,outcome FROM usage_events WHERE id=?", (event_id,)).fetchone()
            if row is None:
                return
            previous = row["outcome"]
            connection.execute("UPDATE usage_events SET outcome=?,tool_count=?,latency_ms=? WHERE id=?", (normalized, max(tool_count, 0), max(latency_ms, 0), event_id))
            tracked = {"completed", "failed", "corrected", "cancelled"}
            if previous != normalized and normalized in tracked:
                if previous in tracked:
                    connection.execute(f"UPDATE usage_aggregates SET {previous}=MAX({previous}-1,0) WHERE skill_name=?", (row["skill_name"],))
                column = normalized
                use_increment = 1 if previous == "unknown" else 0
                connection.execute(
                    f"INSERT INTO usage_aggregates(skill_name,total_uses,{column},total_latency_ms,total_tools) VALUES(?,?,1,?,?) "
                    f"ON CONFLICT(skill_name) DO UPDATE SET total_uses=total_uses+?,{column}={column}+1,total_latency_ms=total_latency_ms+?,total_tools=total_tools+?",
                    (row["skill_name"], use_increment, max(latency_ms, 0), max(tool_count, 0), use_increment,
                     max(latency_ms, 0) if previous == "unknown" else 0, max(tool_count, 0) if previous == "unknown" else 0),
                )
            connection.commit()

    def recent(self, skill_name: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT id,task_summary,source,outcome,tool_count,latency_ms,created_at FROM usage_events WHERE skill_name=? ORDER BY created_at DESC,id DESC LIMIT ?",
                (skill_name.casefold(), min(max(limit, 1), 100)),
            )]

    def aggregate(self, skill_name: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM usage_aggregates WHERE skill_name=?", (skill_name.casefold(),)).fetchone()
        data = dict(row) if row else {"skill_name": skill_name, "total_uses": 0, "completed": 0, "failed": 0, "corrected": 0, "cancelled": 0, "unknown": 0, "total_latency_ms": 0, "total_tools": 0}
        denominator = data["completed"] + data["failed"] + data["corrected"]
        data["success_rate"] = data["completed"] / denominator if denominator else None
        return data

    def purge(self, *, now: datetime | None = None, retention_days: int = 90) -> int:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
        with self._connect() as connection:
            removed = connection.execute("DELETE FROM usage_events WHERE created_at < ?", (cutoff.isoformat(),)).rowcount
            connection.commit()
            return removed

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS usage_events(id TEXT PRIMARY KEY,skill_name TEXT NOT NULL,task_summary TEXT NOT NULL,
                    thread_hash TEXT NOT NULL,source TEXT NOT NULL,outcome TEXT NOT NULL,tool_count INTEGER NOT NULL,
                    latency_ms INTEGER NOT NULL,created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS usage_events_skill_time ON usage_events(skill_name,created_at DESC,id DESC);
                CREATE TABLE IF NOT EXISTS usage_aggregates(skill_name TEXT PRIMARY KEY,total_uses INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,failed INTEGER NOT NULL DEFAULT 0,corrected INTEGER NOT NULL DEFAULT 0,
                    cancelled INTEGER NOT NULL DEFAULT 0,unknown INTEGER NOT NULL DEFAULT 0,total_latency_ms INTEGER NOT NULL DEFAULT 0,total_tools INTEGER NOT NULL DEFAULT 0);
                PRAGMA user_version=1;
            """)


@dataclass
class SkillUsageScope:
    store: SkillUsageIntelligence
    task_summary: str
    thread_id: str
    started: float = field(default_factory=time.monotonic)
    event_ids: list[str] = field(default_factory=list)
    activation_by_skill: dict[str, str] = field(default_factory=dict)
    _token: Any = None

    def __enter__(self) -> "SkillUsageScope":
        self._token = _CURRENT_SCOPE.set(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        outcome = "failed" if exc_type else "unknown"
        if outcome == "failed":
            self.finish(outcome)
        _CURRENT_SCOPE.reset(self._token)

    def activate(self, skill_name: str, source: str) -> str:
        normalized = skill_name.casefold()
        if normalized in self.activation_by_skill:
            return self.activation_by_skill[normalized]
        event_id = self.store.activate(skill_name, task_summary=self.task_summary, thread_id=self.thread_id, source=source)
        self.event_ids.append(event_id)
        self.activation_by_skill[normalized] = event_id
        return event_id

    def finish(self, outcome: str, *, tool_count: int = 0) -> None:
        latency = int((time.monotonic() - self.started) * 1000)
        for event_id in self.event_ids:
            self.store.finish(event_id, outcome=outcome, tool_count=tool_count, latency_ms=latency)


def usage_scope(task_summary: str, thread_id: str, *, store: SkillUsageIntelligence | None = None) -> SkillUsageScope:
    return SkillUsageScope(store or SkillUsageIntelligence(), task_summary, thread_id)


def record_current_activation(skill_name: str, *, source: str = "skill_view") -> str | None:
    scope = _CURRENT_SCOPE.get()
    return scope.activate(skill_name, source) if scope else None
