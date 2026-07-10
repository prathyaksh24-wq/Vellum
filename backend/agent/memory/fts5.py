"""FTS5-backed local index for past Q&A pairs."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3

DB_PATH = Path("data/memory/fts5.db")


class FTS5Memory:
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
                CREATE VIRTUAL TABLE IF NOT EXISTS qa_fts USING fts5(
                    content,
                    created UNINDEXED,
                    thread_id UNINDEXED,
                    source_paths UNINDEXED
                )
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def add_document(
        self,
        *,
        content: str,
        thread_id: str = "default",
        source_paths: list[str] | None = None,
        created: str | None = None,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO qa_fts (content, created, thread_id, source_paths) VALUES (?, ?, ?, ?)",
                (content, created or self._now(), thread_id, json.dumps(source_paths or [])),
            )
            return int(cursor.lastrowid)

    def add_qa_pair(
        self,
        *,
        query: str,
        answer: str,
        thread_id: str = "default",
        source_paths: list[str] | None = None,
    ) -> int:
        return self.add_document(
            content=f"Q: {query}\nA: {answer}",
            thread_id=thread_id,
            source_paths=source_paths,
        )

    def search(self, query: str, *, limit: int = 10) -> list[dict]:
        query = query.strip()
        if not query:
            return []
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT rowid, content, created, thread_id, source_paths, bm25(qa_fts) AS score
                    FROM qa_fts
                    WHERE qa_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (query, max(int(limit), 0)),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    """
                    SELECT rowid, content, created, thread_id, source_paths, 0.0 AS score
                    FROM qa_fts
                    WHERE content LIKE ?
                    ORDER BY rowid DESC
                    LIMIT ?
                    """,
                    (f"%{query}%", max(int(limit), 0)),
                ).fetchall()
        return [self._row(row) for row in rows]

    def recent_documents(self, *, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT rowid, content, created, thread_id, source_paths, 0.0 AS score
                FROM qa_fts
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (max(int(limit), 0),),
            ).fetchall()
        return [self._row(row) for row in rows]

    def source_path_exists(self, source_path: str) -> bool:
        needle = json.dumps(str(source_path))
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM qa_fts
                WHERE source_paths LIKE ?
                LIMIT 1
                """,
                (f"%{needle}%",),
            ).fetchone()
        return row is not None

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        try:
            source_paths = json.loads(row["source_paths"] or "[]")
        except json.JSONDecodeError:
            source_paths = []
        return {
            "id": row["rowid"],
            "content": row["content"],
            "created": row["created"],
            "thread_id": row["thread_id"],
            "source_paths": source_paths,
            "score": row["score"],
        }
