from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from agent.coding.models import (
    AccessMode,
    CodingEvent,
    CodingSession,
    CodingSessionCreate,
    CodingTurn,
    ProviderName,
    utc_now,
)


class CodingSessionStore:
    def __init__(self, db_path: Path = Path("data/memory/coding_sessions.db")) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS coding_sessions (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    provider_session_id TEXT,
                    cwd TEXT NOT NULL,
                    access_mode TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS coding_turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    final_response TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(session_id) REFERENCES coding_sessions(id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_coding_turns_id_session_id
                ON coding_turns(id, session_id);
                CREATE TABLE IF NOT EXISTS coding_events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id TEXT,
                    provider TEXT NOT NULL,
                    type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES coding_sessions(id),
                    FOREIGN KEY(turn_id) REFERENCES coding_turns(id),
                    FOREIGN KEY(turn_id, session_id) REFERENCES coding_turns(id, session_id)
                );
                """
            )

    def create_session(self, body: CodingSessionCreate) -> CodingSession:
        cwd = body.resolved_cwd()
        title = body.title.strip() or Path(cwd).name or "Coding session"
        now = utc_now()
        session = CodingSession(
            id=f"code_{uuid4().hex}",
            provider=body.provider,
            cwd=cwd,
            access_mode=body.access_mode,
            title=title,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO coding_sessions
                (id, provider, provider_session_id, cwd, access_mode, title, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.provider.value,
                    session.provider_session_id,
                    session.cwd,
                    session.access_mode.value,
                    session.title,
                    session.status,
                    session.created_at,
                    session.updated_at,
                ),
            )
        return session

    def get_session(self, session_id: str) -> CodingSession | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM coding_sessions WHERE id = ?", (session_id,)).fetchone()
        return self._session_from_row(row) if row else None

    def list_sessions(self) -> list[CodingSession]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM coding_sessions ORDER BY updated_at DESC, rowid DESC").fetchall()
        return [self._session_from_row(row) for row in rows]

    def set_provider_session_id(self, session_id: str, provider_session_id: str) -> CodingSession:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE coding_sessions SET provider_session_id = ?, updated_at = ? WHERE id = ?",
                (provider_session_id, now, session_id),
            )
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def set_session_status(self, session_id: str, status: str) -> CodingSession:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE coding_sessions SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, session_id),
            )
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def create_turn(self, session_id: str, prompt: str) -> CodingTurn:
        now = utc_now()
        turn = CodingTurn(
            id=f"turn_{uuid4().hex}",
            session_id=session_id,
            prompt=prompt,
            status="running",
            started_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO coding_turns
                (id, session_id, prompt, status, started_at, final_response, error)
                VALUES (?, ?, ?, ?, ?, '', '')
                """,
                (turn.id, turn.session_id, turn.prompt, turn.status, turn.started_at),
            )
        return turn

    def complete_turn(self, turn_id: str, final_response: str = "", error: str = "") -> CodingTurn:
        status = "error" if error else "completed"
        completed_at = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE coding_turns
                SET status = ?, completed_at = ?, final_response = ?, error = ?
                WHERE id = ?
                """,
                (status, completed_at, final_response, error, turn_id),
            )
            row = conn.execute("SELECT * FROM coding_turns WHERE id = ?", (turn_id,)).fetchone()
        if row is None:
            raise KeyError(turn_id)
        return self._turn_from_row(row)

    def record_event(
        self,
        *,
        session_id: str,
        provider: ProviderName,
        event_type: str,
        message: str,
        payload: dict,
        turn_id: str | None = None,
    ) -> CodingEvent:
        event = CodingEvent(
            id=f"evt_{uuid4().hex}",
            session_id=session_id,
            turn_id=turn_id,
            provider=provider,
            type=event_type,
            message=message,
            payload=payload,
            created_at=utc_now(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO coding_events
                (id, session_id, turn_id, provider, type, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.session_id,
                    event.turn_id,
                    event.provider.value,
                    event.type,
                    event.message,
                    json.dumps(event.payload),
                    event.created_at,
                ),
            )
        return event

    def list_events(self, session_id: str) -> list[CodingEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM coding_events WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
                (session_id,),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def _session_from_row(self, row: sqlite3.Row) -> CodingSession:
        return CodingSession(
            id=row["id"],
            provider=ProviderName(row["provider"]),
            provider_session_id=row["provider_session_id"],
            cwd=row["cwd"],
            access_mode=AccessMode(row["access_mode"]),
            title=row["title"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _turn_from_row(self, row: sqlite3.Row) -> CodingTurn:
        return CodingTurn(
            id=row["id"],
            session_id=row["session_id"],
            prompt=row["prompt"],
            status=row["status"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            final_response=row["final_response"],
            error=row["error"],
        )

    def _event_from_row(self, row: sqlite3.Row) -> CodingEvent:
        return CodingEvent(
            id=row["id"],
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            provider=ProviderName(row["provider"]),
            type=row["type"],
            message=row["message"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
        )
