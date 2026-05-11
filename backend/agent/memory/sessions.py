"""Reads and writes thread metadata. Joins checkpoints.db with thread_titles."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from agent.memory.long_term import LongTermMemory


class SessionsReader:
    def __init__(self, *, checkpoints_db: Path, long_term_db: Path) -> None:
        self.checkpoints_db = Path(checkpoints_db)
        self.long_term_db = Path(long_term_db)

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

    def _memory(self) -> LongTermMemory:
        return LongTermMemory(db_path=self.long_term_db)

    def list_sessions(self) -> list[dict[str, Any]]:
        rows = self._checkpoint_rows()
        mem = self._memory()
        return [
            {
                "thread_id": thread_id,
                "title": mem.get_thread_title(thread_id) or thread_id,
                "msgs": msgs,
            }
            for thread_id, msgs in rows
        ]

    def rename(self, thread_id: str, title: str) -> None:
        self._memory().set_thread_title(thread_id, title)

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
        self._memory().delete_thread_title(thread_id)
