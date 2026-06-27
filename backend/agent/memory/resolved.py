"""Resolved-question cache for high-confidence repeated answers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
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

    def find_related(self, query: str, *, min_score: float = 0.28) -> dict | None:
        """Return the best semantically related resolved answer using local lexical overlap.

        This intentionally stays cheap and deterministic. The resolved cache is a
        first-pass "did we already answer this?" layer before expensive tools.
        FTS5/vector stores can still provide broader recall around the returned
        answer.
        """
        query_terms = _expanded_terms(query)
        if not query_terms:
            return None
        now = self._now().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM resolved_questions
                WHERE expires_at > ?
                ORDER BY timestamp DESC
                LIMIT 200
                """,
                (now,),
            ).fetchall()

        best: tuple[float, sqlite3.Row] | None = None
        for row in rows:
            candidate_terms = _expanded_terms(f"{row['query']} {row['answer_summary']}")
            if not candidate_terms:
                continue
            overlap = query_terms.intersection(candidate_terms)
            if not overlap:
                continue
            score = (len(overlap) / max(1, len(query_terms))) * 0.7
            if _has_named_anchor(query_terms, candidate_terms):
                score += 0.25
            if _has_topic_anchor(query_terms, candidate_terms):
                score += 0.15
            score = min(score, 1.0)
            if best is None or score > best[0]:
                best = (score, row)

        if best is None or best[0] < min_score:
            return None
        data = dict(best[1])
        data["sources"] = json.loads(data.pop("sources_json") or "[]")
        data["access_count"] = int(data["access_count"])
        data["related_score"] = round(best[0], 3)
        data["match_type"] = "related"
        return data


_STOPWORDS = {
    "about",
    "after",
    "answer",
    "from",
    "happen",
    "happened",
    "have",
    "into",
    "players",
    "question",
    "that",
    "their",
    "there",
    "these",
    "this",
    "those",
    "traded",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
}


def _expanded_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for raw in re.findall(r"[A-Za-z0-9]+", text.casefold()):
        if len(raw) <= 2 or raw in _STOPWORDS:
            continue
        terms.add(raw)
        if raw.endswith("ies") and len(raw) > 4:
            terms.add(raw[:-3] + "y")
        if raw.endswith("ed") and len(raw) > 4:
            terms.add(raw[:-2])
        if raw.endswith("s") and len(raw) > 4:
            terms.add(raw[:-1])
    return terms


def _has_named_anchor(query_terms: set[str], candidate_terms: set[str]) -> bool:
    return any(term in candidate_terms for term in query_terms if len(term) >= 6)


def _has_topic_anchor(query_terms: set[str], candidate_terms: set[str]) -> bool:
    return bool(query_terms.intersection(candidate_terms).intersection({"trade", "goal", "match", "upload", "video"}))
