"""Resolved-question cache for high-confidence repeated answers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3

DB_PATH = Path("data/memory/resolved.db")


class ResolvedQuestionsCache:
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
                CREATE TABLE IF NOT EXISTS resolved_questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    query_hash TEXT UNIQUE NOT NULL,
                    query TEXT NOT NULL,
                    answer_summary TEXT NOT NULL,
                    sources_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    model TEXT NOT NULL,
                    access_count INTEGER DEFAULT 0,
                    last_accessed TEXT,
                    expires_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _hash(query: str) -> str:
        normalized = " ".join(query.casefold().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def store(
        self,
        *,
        query: str,
        answer_summary: str,
        sources: list[str],
        confidence: float,
        model: str,
    ) -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO resolved_questions (
                    timestamp, query_hash, query, answer_summary, sources_json,
                    confidence, model, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(query_hash) DO UPDATE SET
                    timestamp=excluded.timestamp,
                    query=excluded.query,
                    answer_summary=excluded.answer_summary,
                    sources_json=excluded.sources_json,
                    confidence=excluded.confidence,
                    model=excluded.model,
                    expires_at=excluded.expires_at
                """,
                (
                    now.isoformat(),
                    self._hash(query),
                    query,
                    answer_summary,
                    json.dumps(sources),
                    float(confidence),
                    model,
                    (now + timedelta(days=90)).isoformat(),
                ),
            )

    def get(self, query: str) -> dict | None:
        now = self._now().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM resolved_questions
                WHERE query_hash = ? AND expires_at > ?
                """,
                (self._hash(query), now),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE resolved_questions
                SET access_count = access_count + 1, last_accessed = ?
                WHERE id = ?
                """,
                (now, row["id"]),
            )
        data = dict(row)
        data["sources"] = json.loads(data.pop("sources_json") or "[]")
        data["access_count"] = int(data["access_count"]) + 1
        return data
