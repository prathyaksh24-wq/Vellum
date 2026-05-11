"""SQLite long-term memory for learned facts and query history."""

from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
import sqlite3

DB_PATH = Path("data/memory/long_term.db")


class LongTermMemory:
    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    access_count INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS query_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    query TEXT NOT NULL,
                    answer_source TEXT NOT NULL,
                    confidence REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_category_id ON facts(category, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_query_log_id ON query_log(id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_titles (
                    thread_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def store_fact(self, content: str, category: str = "general") -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO facts (timestamp, category, content) VALUES (?, ?, ?)",
                (self._now(), category, content),
            )
            return int(cursor.lastrowid)

    def log_query(self, query: str, source: str, confidence: float) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO query_log (timestamp, query, answer_source, confidence)
                VALUES (?, ?, ?, ?)
                """,
                (self._now(), query, source, float(confidence)),
            )
            return int(cursor.lastrowid)

    def get_recent_facts(self, category: str | None = None, limit: int = 20) -> list[str]:
        limit = max(int(limit), 0)
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT id, content FROM facts WHERE category=? ORDER BY id DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, content FROM facts ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()

            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"UPDATE facts SET access_count = access_count + 1 WHERE id IN ({placeholders})",
                    ids,
                )
        return [row["content"] for row in rows]

    def get_recent_entries(self, category: str | None = None, limit: int = 20) -> list[dict]:
        limit = max(int(limit), 0)
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT id, timestamp, content, category FROM facts WHERE category=? ORDER BY id DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, timestamp, content, category FROM facts ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [{"id": row["id"], "timestamp": row["timestamp"], "content": row["content"], "category": row["category"]} for row in rows]

    def get_recent_queries(self, limit: int = 20) -> list[dict]:
        limit = max(int(limit), 0)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, query, answer_source, confidence
                FROM query_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_thread_title(self, thread_id: str, title: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO thread_titles (thread_id, title, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(thread_id) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at",
                (thread_id, title, self._now()),
            )

    def get_thread_title(self, thread_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT title FROM thread_titles WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            return row["title"] if row else None

    def delete_thread_title(self, thread_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM thread_titles WHERE thread_id = ?", (thread_id,))

