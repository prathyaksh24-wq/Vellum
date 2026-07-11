"""Reads and writes thread metadata. Joins checkpoints.db with sessions.db."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from agent.config import REPO_ROOT


SESSIONS_DB = REPO_ROOT / "data" / "memory" / "sessions.db"


class SessionsReader:
    def __init__(self, *, checkpoints_db: Path, sessions_db: Path = SESSIONS_DB) -> None:
        self.checkpoints_db = Path(checkpoints_db)
        self.sessions_db = Path(sessions_db)

    def _checkpoint_rows(self) -> list[tuple[str, int]]:
        """Return (thread_id, msg_count) tuples ordered newest-first.

        The langgraph-checkpoint-sqlite schema is:
            checkpoints(thread_id, checkpoint_ns, checkpoint_id,
                        parent_checkpoint_id, type, checkpoint, metadata)
        It has no `ts` column. We sort by MAX(checkpoint_id) descending —
        checkpoint IDs are ULID-style in practice, so lexicographic max
        approximates "most recent activity" well enough for display.
        """
        if not self.checkpoints_db.exists():
            return []
        conn = sqlite3.connect(str(self.checkpoints_db))
        try:
            cur = conn.execute(
                """
                SELECT thread_id,
                       COUNT(*) AS msgs,
                       MAX(checkpoint_id) AS last_ckpt
                FROM checkpoints
                GROUP BY thread_id
                ORDER BY last_ckpt DESC
                """
            )
            return [(r[0], int(r[1])) for r in cur.fetchall()]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def _connect_sessions(self) -> sqlite3.Connection:
        self.sessions_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.sessions_db))
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS thread_titles (
                thread_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        return conn

    def _get_title(self, thread_id: str) -> str | None:
        with self._connect_sessions() as conn:
            row = conn.execute("SELECT title FROM thread_titles WHERE thread_id = ?", (thread_id,)).fetchone()
            return row["title"] if row else None

    def list_sessions(self) -> list[dict[str, Any]]:
        rows = self._checkpoint_rows()
        return [
            {
                "thread_id": thread_id,
                "title": self._get_title(thread_id) or thread_id,
                "msgs": msgs,
            }
            for thread_id, msgs in rows
        ]

    def rename(self, thread_id: str, title: str) -> None:
        with self._connect_sessions() as conn:
            conn.execute(
                """
                INSERT INTO thread_titles (thread_id, title, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    title=excluded.title,
                    updated_at=excluded.updated_at
                """,
                (thread_id, title),
            )

    def delete(self, thread_id: str) -> None:
        if self.checkpoints_db.exists():
            conn = sqlite3.connect(str(self.checkpoints_db))
            try:
                conn.execute(
                    "DELETE FROM checkpoints WHERE thread_id = ?",
                    (thread_id,),
                )
                # Also delete from writes table (langgraph stores intermediates there)
                try:
                    conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
                except sqlite3.OperationalError:
                    pass
                conn.commit()
            finally:
                conn.close()
        with self._connect_sessions() as conn:
            conn.execute("DELETE FROM thread_titles WHERE thread_id = ?", (thread_id,))


class ThreadStateStore:
    """Per-thread state: active project, hot.md rewrite counter.

    Lives in the same sessions.db as thread_titles to share its lifecycle.
    Kept in a separate table so the title schema stays simple.
    """

    def __init__(self, *, sessions_db: Path = SESSIONS_DB) -> None:
        self.sessions_db = Path(sessions_db)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.sessions_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.sessions_db))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_state (
                    thread_id TEXT PRIMARY KEY,
                    active_project TEXT,
                    turns_since_hot_rewrite INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _row(self, thread_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM thread_state WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()

    def get_active_project(self, thread_id: str) -> str | None:
        row = self._row(thread_id)
        return row["active_project"] if row else None

    def set_active_project(self, thread_id: str, slug: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO thread_state (thread_id, active_project, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    active_project = excluded.active_project,
                    updated_at = excluded.updated_at
                """,
                (thread_id, slug),
            )

    def get_turns_since_hot_rewrite(self, thread_id: str) -> int:
        row = self._row(thread_id)
        return int(row["turns_since_hot_rewrite"]) if row else 0

    def bump_turns(self, thread_id: str) -> int:
        """Increment counter atomically. Returns new value.

        Uses BEGIN IMMEDIATE so the UPSERT + SELECT see the same DB snapshot,
        preventing a race when two workers tick the same thread concurrently."""
        conn = self._connect()
        try:
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO thread_state (thread_id, turns_since_hot_rewrite, updated_at)
                VALUES (?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    turns_since_hot_rewrite = turns_since_hot_rewrite + 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (thread_id,),
            )
            row = conn.execute(
                "SELECT turns_since_hot_rewrite FROM thread_state WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            conn.execute("COMMIT")
            return int(row["turns_since_hot_rewrite"])
        finally:
            conn.close()

    def reset_turns(self, thread_id: str) -> None:
        """Zero the counter for an existing thread row.

        No-op when no row exists (since get_turns_since_hot_rewrite already
        returns 0 in that case, the observable behavior is identical to a
        reset). The intended caller — ProjectContext.tick — always bumps
        before resetting, so the row will always exist by then."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE thread_state SET turns_since_hot_rewrite = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE thread_id = ?
                """,
                (thread_id,),
            )
