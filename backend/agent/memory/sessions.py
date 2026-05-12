"""Reads and writes thread metadata. Joins checkpoints.db with sessions.db."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

SESSIONS_DB = Path("data/memory/sessions.db")


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
