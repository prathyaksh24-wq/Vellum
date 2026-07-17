from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from agent.coding.checkpoints import (
    DEFAULT_MAX_CHECKPOINTS_PER_SESSION,
    CodingCheckpoint,
    snapshot_from_payload,
    snapshot_payload,
)
from agent.coding.models import (
    AccessMode,
    CodingEvent,
    CodingSession,
    CodingSessionCreate,
    CodingTurn,
    CodingTurnLimits,
    DEFAULT_MAX_PROVIDER_EVENTS,
    DEFAULT_MAX_RUNTIME_SECONDS,
    ProviderName,
    WorkspaceKind,
    new_trace_id,
    utc_now,
)
from agent.coding.workspace import WorkspaceSnapshot


class CodingTurnConflictError(RuntimeError):
    pass


class CodingSessionStore:
    def __init__(self, db_path: Path = Path("data/memory/coding_sessions.db")) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
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
            conn.execute("PRAGMA journal_mode = WAL")
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
                    updated_at TEXT NOT NULL,
                    tenant_id TEXT NOT NULL DEFAULT 'local',
                    principal_id TEXT NOT NULL DEFAULT 'local-user',
                    workspace_generation INTEGER NOT NULL DEFAULT 1,
                    trace_id TEXT NOT NULL DEFAULT '',
                    source_cwd TEXT NOT NULL DEFAULT '',
                    workspace_kind TEXT NOT NULL DEFAULT 'direct',
                    workspace_root TEXT NOT NULL DEFAULT '',
                    workspace_repository_root TEXT NOT NULL DEFAULT '',
                    workspace_branch TEXT NOT NULL DEFAULT '',
                    workspace_base_commit TEXT NOT NULL DEFAULT ''
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
                    trace_id TEXT NOT NULL DEFAULT '',
                    max_runtime_seconds INTEGER NOT NULL DEFAULT 1800,
                    max_provider_events INTEGER NOT NULL DEFAULT 10000,
                    provider_event_count INTEGER NOT NULL DEFAULT 0,
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
                    trace_id TEXT NOT NULL DEFAULT '',
                    sequence INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(session_id) REFERENCES coding_sessions(id),
                    FOREIGN KEY(turn_id) REFERENCES coding_turns(id),
                    FOREIGN KEY(turn_id, session_id) REFERENCES coding_turns(id, session_id)
                );
                CREATE TABLE IF NOT EXISTS coding_checkpoints (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    before_snapshot_json TEXT NOT NULL,
                    after_snapshot_json TEXT,
                    created_at TEXT NOT NULL,
                    finalized_at TEXT,
                    FOREIGN KEY(session_id) REFERENCES coding_sessions(id),
                    FOREIGN KEY(turn_id, session_id) REFERENCES coding_turns(id, session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_coding_checkpoints_session_created
                ON coding_checkpoints(session_id, created_at DESC);
                """
            )
            self._ensure_column(conn, "coding_sessions", "tenant_id", "TEXT NOT NULL DEFAULT 'local'")
            self._ensure_column(conn, "coding_sessions", "principal_id", "TEXT NOT NULL DEFAULT 'local-user'")
            self._ensure_column(conn, "coding_sessions", "workspace_generation", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "coding_sessions", "trace_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "coding_sessions", "source_cwd", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(
                conn,
                "coding_sessions",
                "workspace_kind",
                "TEXT NOT NULL DEFAULT 'direct'",
            )
            self._ensure_column(conn, "coding_sessions", "workspace_root", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(
                conn,
                "coding_sessions",
                "workspace_repository_root",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(conn, "coding_sessions", "workspace_branch", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(
                conn,
                "coding_sessions",
                "workspace_base_commit",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(conn, "coding_turns", "trace_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(
                conn,
                "coding_turns",
                "max_runtime_seconds",
                f"INTEGER NOT NULL DEFAULT {DEFAULT_MAX_RUNTIME_SECONDS}",
            )
            self._ensure_column(
                conn,
                "coding_turns",
                "max_provider_events",
                f"INTEGER NOT NULL DEFAULT {DEFAULT_MAX_PROVIDER_EVENTS}",
            )
            self._ensure_column(conn, "coding_turns", "provider_event_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "coding_events", "trace_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "coding_events", "sequence", "INTEGER NOT NULL DEFAULT 0")
            self._backfill_runtime_metadata(conn)
            conn.execute("UPDATE coding_sessions SET source_cwd = cwd WHERE source_cwd = ''")
            conn.execute("UPDATE coding_sessions SET workspace_root = cwd WHERE workspace_root = ''")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_coding_events_session_sequence
                ON coding_events(session_id, sequence)
                WHERE sequence > 0
                """
            )

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _backfill_runtime_metadata(conn: sqlite3.Connection) -> None:
        for row in conn.execute("SELECT id FROM coding_sessions WHERE trace_id = ''"):
            conn.execute("UPDATE coding_sessions SET trace_id = ? WHERE id = ?", (new_trace_id(), row["id"]))
        for row in conn.execute("SELECT id FROM coding_turns WHERE trace_id = ''"):
            conn.execute("UPDATE coding_turns SET trace_id = ? WHERE id = ?", (new_trace_id(), row["id"]))

        session_ids = [row["session_id"] for row in conn.execute("SELECT DISTINCT session_id FROM coding_events")]
        for session_id in session_ids:
            rows = conn.execute(
                """
                SELECT rowid, turn_id, sequence
                FROM coding_events
                WHERE session_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (session_id,),
            ).fetchall()
            positive_sequences = {int(row["sequence"]) for row in rows if int(row["sequence"]) > 0}
            next_sequence = max(positive_sequences, default=0) + 1
            if not positive_sequences:
                next_sequence = 1
            for row in rows:
                sequence = int(row["sequence"])
                if sequence <= 0:
                    conn.execute(
                        "UPDATE coding_events SET sequence = ? WHERE rowid = ?",
                        (next_sequence, row["rowid"]),
                    )
                    next_sequence += 1

        conn.execute(
            """
            UPDATE coding_events
            SET trace_id = COALESCE(
                (SELECT trace_id FROM coding_turns WHERE coding_turns.id = coding_events.turn_id),
                (SELECT trace_id FROM coding_sessions WHERE coding_sessions.id = coding_events.session_id),
                ''
            )
            WHERE trace_id = ''
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
            source_cwd=cwd,
            workspace_root=cwd,
            created_at=now,
            updated_at=now,
            tenant_id=body.tenant_id,
            principal_id=body.principal_id,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO coding_sessions
                (id, provider, provider_session_id, cwd, access_mode, title, status, created_at, updated_at,
                 tenant_id, principal_id, workspace_generation, trace_id, source_cwd, workspace_kind,
                 workspace_root, workspace_repository_root, workspace_branch, workspace_base_commit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    session.tenant_id,
                    session.principal_id,
                    session.workspace_generation,
                    session.trace_id,
                    session.source_cwd,
                    session.workspace_kind.value,
                    session.workspace_root,
                    session.workspace_repository_root,
                    session.workspace_branch,
                    session.workspace_base_commit,
                ),
            )
        return session

    def set_session_workspace(
        self,
        session_id: str,
        *,
        source_cwd: str,
        cwd: str,
        workspace_kind: WorkspaceKind,
        workspace_root: str,
        workspace_repository_root: str = "",
        workspace_branch: str = "",
        workspace_base_commit: str = "",
    ) -> CodingSession:
        now = utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE coding_sessions
                SET source_cwd = ?, cwd = ?, workspace_kind = ?, workspace_root = ?,
                    workspace_repository_root = ?, workspace_branch = ?, workspace_base_commit = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    source_cwd,
                    cwd,
                    workspace_kind.value,
                    workspace_root,
                    workspace_repository_root,
                    workspace_branch,
                    workspace_base_commit,
                    now,
                    session_id,
                ),
            )
        if cursor.rowcount == 0:
            raise KeyError(session_id)
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def get_session(self, session_id: str) -> CodingSession | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM coding_sessions WHERE id = ?", (session_id,)).fetchone()
        return self._session_from_row(row) if row else None

    def delete_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM coding_events WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM coding_checkpoints WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM coding_turns WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM coding_sessions WHERE id = ?", (session_id,))

    def list_sessions(
        self,
        *,
        tenant_id: str | None = None,
        principal_id: str | None = None,
    ) -> list[CodingSession]:
        clauses: list[str] = []
        parameters: list[str] = []
        if tenant_id is not None:
            clauses.append("tenant_id = ?")
            parameters.append(tenant_id)
        if principal_id is not None:
            clauses.append("principal_id = ?")
            parameters.append(principal_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM coding_sessions{where} ORDER BY updated_at DESC, rowid DESC",
                parameters,
            ).fetchall()
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

    def create_turn(
        self,
        session_id: str,
        prompt: str,
        *,
        limits: CodingTurnLimits | None = None,
    ) -> CodingTurn:
        effective_limits = limits or CodingTurnLimits()
        now = utc_now()
        turn = CodingTurn(
            id=f"turn_{uuid4().hex}",
            session_id=session_id,
            prompt=prompt,
            status="running",
            started_at=now,
            max_runtime_seconds=effective_limits.max_runtime_seconds,
            max_provider_events=effective_limits.max_provider_events,
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            session_row = conn.execute(
                "SELECT status FROM coding_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session_row is not None and session_row["status"] == "running":
                raise CodingTurnConflictError("Coding session already has a running turn.")
            conn.execute(
                """
                INSERT INTO coding_turns
                (id, session_id, prompt, status, started_at, final_response, error, trace_id,
                 max_runtime_seconds, max_provider_events, provider_event_count)
                VALUES (?, ?, ?, ?, ?, '', '', ?, ?, ?, 0)
                """,
                (
                    turn.id,
                    turn.session_id,
                    turn.prompt,
                    turn.status,
                    turn.started_at,
                    turn.trace_id,
                    turn.max_runtime_seconds,
                    turn.max_provider_events,
                ),
            )
            conn.execute(
                "UPDATE coding_sessions SET status = 'running', updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        return turn

    def claim_provider_event(self, turn_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE coding_turns
                SET provider_event_count = provider_event_count + 1
                WHERE id = ?
                  AND status = 'running'
                  AND provider_event_count < max_provider_events
                """,
                (turn_id,),
            )
        return cursor.rowcount == 1

    def complete_turn(self, turn_id: str, final_response: str = "", error: str = "") -> CodingTurn:
        status = "error" if error else "completed"
        return self.finish_turn(turn_id, status=status, final_response=final_response, error=error)

    def finish_turn(
        self,
        turn_id: str,
        *,
        status: str,
        final_response: str = "",
        error: str = "",
    ) -> CodingTurn:
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

    def finish_running_turn(
        self,
        turn_id: str,
        *,
        status: str,
        final_response: str = "",
        error: str = "",
    ) -> CodingTurn | None:
        completed_at = utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE coding_turns
                SET status = ?, completed_at = ?, final_response = ?, error = ?
                WHERE id = ? AND status = 'running'
                """,
                (status, completed_at, final_response, error, turn_id),
            )
            row = conn.execute("SELECT * FROM coding_turns WHERE id = ?", (turn_id,)).fetchone()
        if row is None:
            raise KeyError(turn_id)
        if cursor.rowcount == 0:
            return None
        return self._turn_from_row(row)

    def get_turn(self, turn_id: str) -> CodingTurn | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM coding_turns WHERE id = ?", (turn_id,)).fetchone()
        return self._turn_from_row(row) if row else None

    def get_running_turn(self, session_id: str) -> CodingTurn | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM coding_turns
                WHERE session_id = ? AND status = 'running'
                ORDER BY started_at DESC, rowid DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return self._turn_from_row(row) if row else None

    def create_checkpoint(
        self,
        *,
        session_id: str,
        turn_id: str,
        before: WorkspaceSnapshot,
        max_per_session: int = DEFAULT_MAX_CHECKPOINTS_PER_SESSION,
    ) -> CodingCheckpoint:
        if max_per_session < 1:
            raise ValueError("max_per_session must be positive")
        checkpoint = CodingCheckpoint(
            id=f"checkpoint_{uuid4().hex}",
            session_id=session_id,
            turn_id=turn_id,
            status="started",
            before=before,
            after=None,
            created_at=utc_now(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO coding_checkpoints
                (id, session_id, turn_id, status, before_snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.id,
                    checkpoint.session_id,
                    checkpoint.turn_id,
                    checkpoint.status,
                    json.dumps(snapshot_payload(before, include_patch=True), ensure_ascii=False),
                    checkpoint.created_at,
                ),
            )
            stale_rows = conn.execute(
                """
                SELECT id FROM coding_checkpoints
                WHERE session_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT -1 OFFSET ?
                """,
                (session_id, max_per_session),
            ).fetchall()
            if stale_rows:
                conn.executemany(
                    "DELETE FROM coding_checkpoints WHERE id = ?",
                    [(row["id"],) for row in stale_rows],
                )
        return checkpoint

    def finish_checkpoint(
        self,
        turn_id: str,
        *,
        status: str,
        after: WorkspaceSnapshot,
    ) -> CodingCheckpoint | None:
        finalized_at = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE coding_checkpoints
                SET status = ?, after_snapshot_json = ?, finalized_at = ?
                WHERE turn_id = ? AND finalized_at IS NULL
                """,
                (
                    status,
                    json.dumps(snapshot_payload(after, include_patch=True), ensure_ascii=False),
                    finalized_at,
                    turn_id,
                ),
            )
            row = conn.execute(
                "SELECT * FROM coding_checkpoints WHERE turn_id = ?",
                (turn_id,),
            ).fetchone()
        return self._checkpoint_from_row(row) if row else None

    def get_checkpoint(self, checkpoint_id: str) -> CodingCheckpoint | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM coding_checkpoints WHERE id = ?",
                (checkpoint_id,),
            ).fetchone()
        return self._checkpoint_from_row(row) if row else None

    def get_checkpoint_for_turn(self, turn_id: str) -> CodingCheckpoint | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM coding_checkpoints WHERE turn_id = ?",
                (turn_id,),
            ).fetchone()
        return self._checkpoint_from_row(row) if row else None

    def list_checkpoints(self, session_id: str) -> list[CodingCheckpoint]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM coding_checkpoints
                WHERE session_id = ?
                ORDER BY created_at DESC, rowid DESC
                """,
                (session_id,),
            ).fetchall()
        return [self._checkpoint_from_row(row) for row in rows]

    def list_running_turns(self) -> list[CodingTurn]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM coding_turns WHERE status = 'running' ORDER BY started_at ASC, rowid ASC"
            ).fetchall()
        return [self._turn_from_row(row) for row in rows]

    def record_event(
        self,
        *,
        session_id: str,
        provider: ProviderName,
        event_type: str,
        message: str,
        payload: dict,
        turn_id: str | None = None,
        trace_id: str | None = None,
    ) -> CodingEvent:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            session_row = conn.execute(
                "SELECT trace_id FROM coding_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session_row is None:
                raise sqlite3.IntegrityError("coding session does not exist")
            effective_trace_id = trace_id
            if effective_trace_id is None and turn_id is not None:
                turn_row = conn.execute(
                    "SELECT trace_id FROM coding_turns WHERE id = ? AND session_id = ?",
                    (turn_id, session_id),
                ).fetchone()
                effective_trace_id = str(turn_row["trace_id"]) if turn_row is not None else None
            effective_trace_id = effective_trace_id or str(session_row["trace_id"])
            sequence = int(
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM coding_events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
            )
            event = CodingEvent(
                id=f"evt_{uuid4().hex}",
                session_id=session_id,
                turn_id=turn_id,
                provider=provider,
                type=event_type,
                message=message,
                payload=payload,
                created_at=utc_now(),
                trace_id=effective_trace_id,
                sequence=sequence,
            )
            conn.execute(
                """
                INSERT INTO coding_events
                (id, session_id, turn_id, provider, type, message, payload_json, created_at, trace_id, sequence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    event.trace_id,
                    event.sequence,
                ),
            )
        return event

    def list_events(self, session_id: str, *, after_sequence: int = 0) -> list[CodingEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM coding_events
                WHERE session_id = ? AND sequence > ?
                ORDER BY sequence ASC
                """,
                (session_id, max(0, after_sequence)),
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
            source_cwd=row["source_cwd"],
            workspace_kind=WorkspaceKind(row["workspace_kind"]),
            workspace_root=row["workspace_root"],
            workspace_repository_root=row["workspace_repository_root"],
            workspace_branch=row["workspace_branch"],
            workspace_base_commit=row["workspace_base_commit"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tenant_id=row["tenant_id"],
            principal_id=row["principal_id"],
            workspace_generation=row["workspace_generation"],
            trace_id=row["trace_id"],
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
            trace_id=row["trace_id"],
            max_runtime_seconds=row["max_runtime_seconds"],
            max_provider_events=row["max_provider_events"],
            provider_event_count=row["provider_event_count"],
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
            trace_id=row["trace_id"],
            sequence=row["sequence"],
        )

    def _checkpoint_from_row(self, row: sqlite3.Row) -> CodingCheckpoint:
        before = snapshot_from_payload(json.loads(row["before_snapshot_json"]))
        after_payload = json.loads(row["after_snapshot_json"]) if row["after_snapshot_json"] else None
        return CodingCheckpoint(
            id=row["id"],
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            status=row["status"],
            before=before,
            after=snapshot_from_payload(after_payload) if after_payload else None,
            created_at=row["created_at"],
            finalized_at=row["finalized_at"],
        )
