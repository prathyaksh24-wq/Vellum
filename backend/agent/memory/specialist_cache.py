from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Literal

from agent.agents.base import SpecialistResponse
from agent.profiles import CachePolicy


CacheStatus = Literal["hit", "miss", "stale", "bypass"]


@dataclass(frozen=True)
class CacheDecision:
    status: CacheStatus
    reason: str
    response: SpecialistResponse | None = None
    captured_at: str = ""
    expires_at: str = ""


class SpecialistResponseCache:
    def __init__(self, db_path: str | Path, *, now: Callable[[], datetime] | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now or (lambda: datetime.now(UTC))
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS specialist_response_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id TEXT NOT NULL,
                    profile_version INTEGER NOT NULL,
                    query_hash TEXT NOT NULL,
                    query TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    freshness_class TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    captured_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    result_hash TEXT NOT NULL,
                    UNIQUE(profile_id, profile_version, query_hash)
                )
                """
            )

    def lookup(
        self,
        *,
        profile_id: str,
        profile_version: int,
        query: str,
        policy: CachePolicy,
    ) -> CacheDecision:
        bypass = _bypass_reason(query, policy)
        if bypass:
            return CacheDecision(status="bypass", reason=bypass)

        with self._connect() as conn:
            exact = conn.execute(
                """
                SELECT * FROM specialist_response_cache
                WHERE profile_id = ? AND profile_version = ? AND query_hash = ?
                """,
                (profile_id, profile_version, _query_hash(query)),
            ).fetchone()
            if exact is not None:
                return self._decision_from_row(conn, exact, reason="exact_query")

            rows = conn.execute(
                """
                SELECT * FROM specialist_response_cache
                WHERE profile_id = ? AND profile_version = ?
                ORDER BY captured_at DESC LIMIT 100
                """,
                (profile_id, profile_version),
            ).fetchall()
            related = _best_related(query, rows)
            if related is not None:
                return self._decision_from_row(conn, related, reason="related_query")
        return CacheDecision(status="miss", reason="not_found")

    def store(
        self,
        *,
        profile_id: str,
        profile_version: int,
        query: str,
        response: SpecialistResponse,
        policy: CachePolicy,
    ) -> bool:
        if response.status != "answered" or response.action_request:
            return False
        now = self._utc_now()
        freshness = classify_freshness(query)
        ttl_seconds = {
            "live": policy.live_ttl_seconds,
            "historical": policy.historical_ttl_seconds,
            "default": policy.default_ttl_seconds,
        }[freshness]
        payload = response.model_dump_json()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO specialist_response_cache (
                    profile_id, profile_version, query_hash, query, response_json,
                    freshness_class, confidence, captured_at, expires_at, result_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, profile_version, query_hash) DO UPDATE SET
                    query=excluded.query,
                    response_json=excluded.response_json,
                    freshness_class=excluded.freshness_class,
                    confidence=excluded.confidence,
                    captured_at=excluded.captured_at,
                    expires_at=excluded.expires_at,
                    result_hash=excluded.result_hash
                """,
                (
                    profile_id,
                    profile_version,
                    _query_hash(query),
                    query.strip(),
                    payload,
                    freshness,
                    float(response.confidence),
                    now.isoformat(),
                    (now + timedelta(seconds=ttl_seconds)).isoformat(),
                    hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                ),
            )
        return True

    def _decision_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row, *, reason: str) -> CacheDecision:
        try:
            response = SpecialistResponse.model_validate_json(row["response_json"])
        except (ValueError, TypeError, json.JSONDecodeError):
            conn.execute("DELETE FROM specialist_response_cache WHERE id = ?", (row["id"],))
            return CacheDecision(status="miss", reason="invalid_payload")
        status: CacheStatus = "hit" if row["expires_at"] > self._utc_now().isoformat() else "stale"
        return CacheDecision(
            status=status,
            reason=reason,
            response=response,
            captured_at=row["captured_at"],
            expires_at=row["expires_at"],
        )

    def _utc_now(self) -> datetime:
        value = self._now()
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def classify_freshness(query: str) -> Literal["live", "default", "historical"]:
    lowered = query.casefold()
    if any(term in lowered for term in ("live score", "right now", "breaking", "in progress", "currently")):
        return "live"
    if any(term in lowered for term in ("historical", "history", "all-time", "all time", "transcript", "career")):
        return "historical"
    if re.search(r"\b(?:19|20)\d{2}\b", lowered):
        return "historical"
    return "default"


def _bypass_reason(query: str, policy: CachePolicy) -> str:
    lowered = query.casefold()
    for term in policy.bypass_terms:
        clean = term.casefold().strip()
        if clean and re.search(rf"(?<!\w){re.escape(clean)}(?!\w)", lowered):
            return f"live_intent:{clean}"
    return ""


def _query_hash(query: str) -> str:
    normalized = " ".join(query.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


_STOPWORDS = {"a", "an", "the", "do", "does", "did", "in", "on", "at", "to", "for", "who", "what", "when"}


def _terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", text.casefold()) if term not in _STOPWORDS and len(term) > 1}


def _best_related(query: str, rows: list[sqlite3.Row]) -> sqlite3.Row | None:
    query_terms = _terms(query)
    if len(query_terms) < 2:
        return None
    best: tuple[float, sqlite3.Row] | None = None
    for row in rows:
        candidate_terms = _terms(str(row["query"]))
        if not candidate_terms:
            continue
        score = len(query_terms & candidate_terms) / len(query_terms | candidate_terms)
        if score >= 0.8 and (best is None or score > best[0]):
            best = (score, row)
    return best[1] if best is not None else None
