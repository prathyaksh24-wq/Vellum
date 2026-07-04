from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from agent.organization.models import AgentMessage, MemoryRecord, TaskRoom


class OrganizationStore:
    def __init__(self, db_path: str | Path = Path("data/organization/organization.db")) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
                    text TEXT NOT NULL, confidence REAL NOT NULL, parent_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_rooms (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, purpose TEXT NOT NULL,
                    participants_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS agent_messages (
                    id TEXT PRIMARY KEY, room_id TEXT NOT NULL, sender TEXT NOT NULL,
                    recipient TEXT NOT NULL, type TEXT NOT NULL, claim TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, confidence REAL NOT NULL, created_at TEXT NOT NULL,
                    task TEXT NOT NULL DEFAULT '', visibility TEXT NOT NULL DEFAULT 'recipient'
                );
                """
            )
            _ensure_column(conn, "task_rooms", "expires_at", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "agent_messages", "task", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "agent_messages", "visibility", "TEXT NOT NULL DEFAULT 'recipient'")

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add_memory(self, owner: str, scope: str, text: str, confidence: float, parent_id: str | None = None) -> MemoryRecord:
        record = MemoryRecord(str(uuid4()), owner, scope, text, float(confidence), parent_id, _now())
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO memory_records VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.owner,
                    record.scope,
                    record.text,
                    record.confidence,
                    record.parent_id,
                    record.created_at,
                ),
            )
        return record

    def get(self, record_id: str) -> MemoryRecord | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM memory_records WHERE id = ?", (record_id,)).fetchone()
        return MemoryRecord(**dict(row)) if row else None

    def search(self, query: str) -> list[MemoryRecord]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM memory_records WHERE text LIKE ? ORDER BY created_at DESC", (f"%{query}%",)).fetchall()
        return [MemoryRecord(**dict(row)) for row in rows]

    def add_room(self, owner: str, purpose: str, participants: list[str], expires_at: str = "") -> TaskRoom:
        all_participants = tuple(dict.fromkeys([owner, *participants]))
        room = TaskRoom(str(uuid4()), owner, purpose, all_participants, "active", _now(), expires_at)
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO task_rooms (id, owner, purpose, participants_json, status, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (room.id, room.owner, room.purpose, json.dumps(room.participants), room.status, room.created_at, room.expires_at),
            )
        return room

    def get_room(self, room_id: str) -> TaskRoom | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM task_rooms WHERE id = ?", (room_id,)).fetchone()
        if not row:
            return None
        return TaskRoom(row["id"], row["owner"], row["purpose"], tuple(json.loads(row["participants_json"])), row["status"], row["created_at"], row["expires_at"])

    def list_rooms(self) -> list[TaskRoom]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM task_rooms ORDER BY created_at DESC, id").fetchall()
        return [
            TaskRoom(row["id"], row["owner"], row["purpose"], tuple(json.loads(row["participants_json"])), row["status"], row["created_at"], row["expires_at"])
            for row in rows
        ]

    def close_room(self, room_id: str) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE task_rooms SET status = 'completed' WHERE id = ?", (room_id,))

    def update_room(self, room_id: str, *, participants: tuple[str, ...] | None = None, status: str | None = None) -> None:
        with self.connection() as conn:
            if participants is not None:
                conn.execute("UPDATE task_rooms SET participants_json = ? WHERE id = ?", (json.dumps(participants), room_id))
            if status is not None:
                conn.execute("UPDATE task_rooms SET status = ? WHERE id = ?", (status, room_id))

    def add_message(self, room_id: str, sender: str, recipient: str, message_type: str, claim: str, evidence_refs: list[str], confidence: float, *, task: str = "", visibility: str = "recipient") -> AgentMessage:
        message = AgentMessage(str(uuid4()), room_id, sender, recipient, message_type, claim, tuple(evidence_refs), float(confidence), _now(), task, visibility)
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO agent_messages (id, room_id, sender, recipient, type, claim, evidence_json, confidence, created_at, task, visibility) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (message.id, room_id, sender, recipient, message_type, claim, json.dumps(evidence_refs), confidence, message.created_at, task, visibility),
            )
        return message

    def messages(self, room_id: str) -> list[AgentMessage]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM agent_messages WHERE room_id = ? ORDER BY created_at, id", (room_id,)).fetchall()
        return [
            AgentMessage(row["id"], row["room_id"], row["sender"], row["recipient"], row["type"], row["claim"], tuple(json.loads(row["evidence_json"])), row["confidence"], row["created_at"], row["task"], row["visibility"])
            for row in rows
        ]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
