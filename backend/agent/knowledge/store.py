"""SQLite-backed canonical evidence store for Vellum Personal Intelligence.

The store is deliberately local-first and dependency-light. Large source bodies
are content-addressed and gzip-compressed outside SQLite; the database owns
identity, provenance, lineage, policy, and temporal state.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from agent.knowledge.models import (
    ContextPackRequest,
    IngestionJobInput,
    ObservationActor,
    ObservationInput,
    ProjectionInput,
    SourceItemInput,
    SyncCursorInput,
    UserSignalInput,
)
from agent.privacy.scrubber import PrivacyScrubber


SCHEMA_VERSION = 3


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class BlobStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def put_text(self, content: str) -> tuple[str, str, int]:
        raw = content.encode("utf-8")
        digest = _content_hash(raw)
        relative = Path("sha256") / digest[:2] / f"{digest}.txt.gz"
        target = self.root / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            handle, temp_name = tempfile.mkstemp(prefix=f".{digest}.", suffix=".tmp", dir=target.parent)
            try:
                with os.fdopen(handle, "wb") as raw_file:
                    with gzip.GzipFile(fileobj=raw_file, mode="wb", mtime=0) as compressed:
                        compressed.write(raw)
                os.replace(temp_name, target)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
        return digest, relative.as_posix(), len(raw)

    def read_text(self, relative_path: str) -> str:
        target = (self.root / relative_path).resolve()
        root = self.root.resolve()
        if not target.is_relative_to(root):
            raise ValueError("Blob path escapes the knowledge store.")
        with gzip.open(target, "rt", encoding="utf-8") as handle:
            return handle.read()


class KnowledgeStore:
    """Canonical source, evidence, observation, and projection repository."""

    def __init__(self, db_path: str | Path, blob_root: str | Path) -> None:
        self.db_path = Path(db_path)
        self.blobs = BlobStore(blob_root)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Knowledge database schema {version} is newer than supported schema {SCHEMA_VERSION}."
                )
            if version == 0:
                self._create_schema(connection)
                connection.execute("PRAGMA user_version = 1")
                version = 1
            if version < 2:
                self._migrate_v2(connection)
                connection.execute("PRAGMA user_version = 2")
                version = 2
            if version < 3:
                self._migrate_v3(connection)
                connection.execute("PRAGMA user_version = 3")

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE sources (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                external_id TEXT NOT NULL,
                account_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                uri TEXT NOT NULL DEFAULT '',
                source_path TEXT NOT NULL DEFAULT '',
                sensitivity TEXT NOT NULL,
                external_policy TEXT NOT NULL,
                trust TEXT NOT NULL,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                current_version_id TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(kind, external_id)
            );

            CREATE TABLE source_versions (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                version_number INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                blob_path TEXT NOT NULL DEFAULT '',
                byte_size INTEGER NOT NULL DEFAULT 0,
                published_at TEXT NOT NULL DEFAULT '',
                observed_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(source_id, content_hash)
            );

            CREATE INDEX source_versions_source_idx ON source_versions(source_id, version_number DESC);
            CREATE INDEX sources_kind_idx ON sources(kind, updated_at DESC);

            CREATE TABLE entities (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                sensitivity TEXT NOT NULL DEFAULT 'private',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(entity_type, normalized_name)
            );

            CREATE TABLE entity_aliases (
                id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                alias TEXT NOT NULL,
                normalized_alias TEXT NOT NULL,
                source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                UNIQUE(entity_id, normalized_alias)
            );

            CREATE TABLE relationships (
                id TEXT PRIMARY KEY,
                source_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                relationship_type TEXT NOT NULL,
                target_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                confidence REAL NOT NULL DEFAULT 0,
                valid_from TEXT NOT NULL DEFAULT '',
                valid_to TEXT NOT NULL DEFAULT '',
                evidence_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(source_entity_id, relationship_type, target_entity_id)
            );

            CREATE TABLE observations (
                id TEXT PRIMARY KEY,
                event_key TEXT NOT NULL UNIQUE,
                origin TEXT NOT NULL,
                actor TEXT NOT NULL,
                trigger TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                sensitivity TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                observed_at TEXT NOT NULL,
                expires_at TEXT NOT NULL DEFAULT '',
                promotion_status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX observations_origin_idx ON observations(origin, observed_at DESC);
            CREATE INDEX observations_source_idx ON observations(source_id, observed_at DESC);

            CREATE TABLE claims (
                id TEXT PRIMARY KEY,
                subject_entity_id TEXT REFERENCES entities(id) ON DELETE SET NULL,
                predicate TEXT NOT NULL,
                object_text TEXT NOT NULL DEFAULT '',
                object_entity_id TEXT REFERENCES entities(id) ON DELETE SET NULL,
                classification TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                temporal_state TEXT NOT NULL DEFAULT 'current',
                valid_from TEXT NOT NULL DEFAULT '',
                valid_to TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'candidate',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE claim_evidence (
                id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
                source_version_id TEXT REFERENCES source_versions(id) ON DELETE SET NULL,
                observation_id TEXT REFERENCES observations(id) ON DELETE SET NULL,
                locator TEXT NOT NULL DEFAULT '',
                stance TEXT NOT NULL DEFAULT 'supports',
                created_at TEXT NOT NULL,
                UNIQUE(claim_id, source_version_id, observation_id, locator)
            );

            CREATE TABLE user_signals (
                id TEXT PRIMARY KEY,
                entity_id TEXT REFERENCES entities(id) ON DELETE SET NULL,
                signal_type TEXT NOT NULL,
                value REAL NOT NULL DEFAULT 0,
                weight REAL NOT NULL DEFAULT 0,
                actor TEXT NOT NULL,
                source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
                observation_id TEXT REFERENCES observations(id) ON DELETE SET NULL,
                observed_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE preference_states (
                id TEXT PRIMARY KEY,
                subject_key TEXT NOT NULL UNIQUE,
                entity_id TEXT REFERENCES entities(id) ON DELETE SET NULL,
                category TEXT NOT NULL,
                current_score REAL NOT NULL DEFAULT 0,
                trend TEXT NOT NULL DEFAULT 'stable',
                lifecycle TEXT NOT NULL DEFAULT 'discovered',
                confidence REAL NOT NULL DEFAULT 0,
                historical_peak REAL NOT NULL DEFAULT 0,
                windows_json TEXT NOT NULL DEFAULT '{}',
                evidence_count INTEGER NOT NULL DEFAULT 0,
                last_meaningful_engagement TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE derived_insights (
                id TEXT PRIMARY KEY,
                insight_type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                classification TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                external_allowed INTEGER NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 0,
                lineage_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'candidate',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE projections (
                id TEXT PRIMARY KEY,
                canonical_type TEXT NOT NULL,
                canonical_id TEXT NOT NULL,
                target TEXT NOT NULL,
                target_ref TEXT NOT NULL,
                projection_type TEXT NOT NULL,
                content_hash TEXT NOT NULL DEFAULT '',
                generated_by TEXT NOT NULL,
                do_not_reingest INTEGER NOT NULL DEFAULT 1,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                last_exported_at TEXT NOT NULL,
                UNIQUE(target, target_ref)
            );

            CREATE TABLE sync_cursors (
                id TEXT PRIMARY KEY,
                connector TEXT NOT NULL,
                account_id TEXT NOT NULL,
                cursor TEXT NOT NULL DEFAULT '',
                state_json TEXT NOT NULL DEFAULT '{}',
                last_success_at TEXT NOT NULL DEFAULT '',
                last_error_at TEXT NOT NULL DEFAULT '',
                last_error_code TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(connector, account_id)
            );

            CREATE TABLE ingestion_jobs (
                id TEXT PRIMARY KEY,
                connector TEXT NOT NULL,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                requested_by TEXT NOT NULL,
                stats_json TEXT NOT NULL DEFAULT '{}',
                error_code TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT '',
                completed_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE context_packs (
                id TEXT PRIMARY KEY,
                purpose TEXT NOT NULL,
                destination TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                query_text TEXT NOT NULL,
                token_budget INTEGER NOT NULL,
                citations_required INTEGER NOT NULL DEFAULT 1,
                evidence_json TEXT NOT NULL DEFAULT '[]',
                policy_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL DEFAULT ''
            );
            """
        )

    @staticmethod
    def _migrate_v2(connection: sqlite3.Connection) -> None:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(user_signals)").fetchall()}
        additions = {
            "subject_key": "TEXT NOT NULL DEFAULT ''",
            "category": "TEXT NOT NULL DEFAULT 'general'",
            "evidence_class": "TEXT NOT NULL DEFAULT 'engagement'",
            "eligible": "INTEGER NOT NULL DEFAULT 0",
            "event_key": "TEXT NOT NULL DEFAULT ''",
            "sensitivity": "TEXT NOT NULL DEFAULT 'private'",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE user_signals ADD COLUMN {name} {definition}")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS user_signals_event_key ON user_signals(event_key) WHERE event_key <> ''"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS user_signals_subject_time ON user_signals(subject_key, observed_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS preference_states_category_score ON preference_states(category, current_score DESC)"
        )

    @staticmethod
    def _migrate_v3(connection: sqlite3.Connection) -> None:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(ingestion_jobs)").fetchall()}
        if "account_id" not in columns:
            connection.execute("ALTER TABLE ingestion_jobs ADD COLUMN account_id TEXT NOT NULL DEFAULT ''")
        if "attempt_count" not in columns:
            connection.execute("ALTER TABLE ingestion_jobs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 1")
        if "lease_expires_at" not in columns:
            connection.execute("ALTER TABLE ingestion_jobs ADD COLUMN lease_expires_at TEXT NOT NULL DEFAULT ''")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS ingestion_jobs_connector_account_time "
            "ON ingestion_jobs(connector, account_id, created_at DESC)"
        )

    def upsert_source(self, item: SourceItemInput) -> dict[str, Any]:
        source_id = _stable_id("src", item.kind.casefold(), item.external_id)
        observed_at = _iso(item.observed_at) or _now()
        published_at = _iso(item.published_at)
        metadata_json = _json(item.metadata)
        content_bytes = (item.content or "").encode("utf-8")
        fingerprint_input = content_bytes or metadata_json.encode("utf-8")
        digest = _content_hash(fingerprint_input)
        blob_path = ""
        byte_size = len(content_bytes)
        if item.content is not None:
            digest, blob_path, byte_size = self.blobs.put_text(item.content)
        now = _now()
        version_id = _stable_id("ver", source_id, digest)

        with self._connect() as connection:
            existing = connection.execute("SELECT id FROM sources WHERE id = ?", (source_id,)).fetchone()
            connection.execute(
                """
                INSERT INTO sources (
                    id, kind, external_id, account_id, title, uri, source_path,
                    sensitivity, external_policy, trust, status, metadata_json,
                    first_seen_at, last_seen_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    account_id = excluded.account_id,
                    title = excluded.title,
                    uri = excluded.uri,
                    source_path = excluded.source_path,
                    sensitivity = excluded.sensitivity,
                    external_policy = excluded.external_policy,
                    trust = excluded.trust,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                (
                    source_id,
                    item.kind,
                    item.external_id,
                    item.account_id,
                    item.title,
                    item.uri,
                    item.source_path,
                    item.sensitivity.value,
                    item.external_policy.value,
                    item.trust,
                    item.status,
                    metadata_json,
                    observed_at,
                    observed_at,
                    now,
                    now,
                ),
            )
            version_exists = connection.execute(
                "SELECT id FROM source_versions WHERE source_id = ? AND content_hash = ?",
                (source_id, digest),
            ).fetchone()
            if version_exists is None:
                version_number = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(version_number), 0) + 1 FROM source_versions WHERE source_id = ?",
                        (source_id,),
                    ).fetchone()[0]
                )
                connection.execute(
                    """
                    INSERT INTO source_versions (
                        id, source_id, version_number, content_hash, blob_path, byte_size,
                        published_at, observed_at, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        source_id,
                        version_number,
                        digest,
                        blob_path,
                        byte_size,
                        published_at,
                        observed_at,
                        metadata_json,
                        now,
                    ),
                )
            else:
                version_id = str(version_exists["id"])
            connection.execute(
                "UPDATE sources SET current_version_id = ?, updated_at = ? WHERE id = ?",
                (version_id, now, source_id),
            )
        return {
            "source_id": source_id,
            "version_id": version_id,
            "created": existing is None,
            "version_created": version_exists is None,
            "content_hash": digest,
            "byte_size": byte_size,
        }

    def record_observation(self, item: ObservationInput) -> dict[str, Any]:
        observed_at = _iso(item.observed_at) or _now()
        canonical_payload = _json(item.payload)
        event_key = item.event_key.strip() or _stable_id(
            "evtkey",
            item.origin,
            item.actor.value,
            item.action,
            item.source_id or "",
            canonical_payload,
        )
        observation_id = _stable_id("obs", event_key)
        now = _now()
        with self._connect() as connection:
            existing = connection.execute("SELECT id FROM observations WHERE event_key = ?", (event_key,)).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO observations (
                        id, event_key, origin, actor, trigger, action, source_id,
                        payload_json, sensitivity, confidence, observed_at, expires_at,
                        promotion_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation_id,
                        event_key,
                        item.origin,
                        item.actor.value,
                        item.trigger,
                        item.action,
                        item.source_id,
                        canonical_payload,
                        item.sensitivity.value,
                        float(item.confidence),
                        observed_at,
                        _iso(item.expires_at),
                        item.promotion_status.value,
                        now,
                    ),
                )
            else:
                observation_id = str(existing["id"])
        return {"observation_id": observation_id, "event_key": event_key, "created": existing is None}

    def register_projection(self, item: ProjectionInput) -> dict[str, Any]:
        projection_id = _stable_id("prj", item.target, item.target_ref)
        now = _now()
        with self._connect() as connection:
            existing = connection.execute("SELECT id FROM projections WHERE id = ?", (projection_id,)).fetchone()
            connection.execute(
                """
                INSERT INTO projections (
                    id, canonical_type, canonical_id, target, target_ref,
                    projection_type, content_hash, generated_by, do_not_reingest,
                    metadata_json, last_exported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    canonical_type = excluded.canonical_type,
                    canonical_id = excluded.canonical_id,
                    projection_type = excluded.projection_type,
                    content_hash = excluded.content_hash,
                    generated_by = excluded.generated_by,
                    do_not_reingest = excluded.do_not_reingest,
                    metadata_json = excluded.metadata_json,
                    last_exported_at = excluded.last_exported_at
                """,
                (
                    projection_id,
                    item.canonical_type,
                    item.canonical_id,
                    item.target,
                    item.target_ref,
                    item.projection_type,
                    item.content_hash,
                    item.generated_by,
                    int(item.do_not_reingest),
                    _json(item.metadata),
                    now,
                ),
            )
        return {"projection_id": projection_id, "created": existing is None}

    def record_user_signal(self, item: UserSignalInput) -> dict[str, Any]:
        signal_id = _stable_id("sig", item.event_key)
        observed_at = _iso(item.observed_at) or _now()
        eligible_actor = item.actor not in {ObservationActor.AGENT, ObservationActor.SCHEDULED}
        eligible = bool(item.preference_evidence and eligible_actor)
        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id, eligible FROM user_signals WHERE event_key = ?",
                (item.event_key,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO user_signals (
                        id, entity_id, signal_type, value, weight, actor, source_id,
                        observation_id, observed_at, metadata_json, created_at,
                        subject_key, category, evidence_class, eligible, event_key,
                        sensitivity
                    ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal_id,
                        item.signal_type,
                        float(item.value),
                        float(item.weight),
                        item.actor.value,
                        item.source_id,
                        item.observation_id,
                        observed_at,
                        _json(item.metadata),
                        now,
                        item.subject_key,
                        item.category,
                        item.evidence_class.value,
                        int(eligible),
                        item.event_key,
                        item.sensitivity.value,
                    ),
                )
            else:
                signal_id = str(existing["id"])
                eligible = bool(existing["eligible"])
        state = self.recompute_preference(item.subject_key)
        return {
            "signal_id": signal_id,
            "created": existing is None,
            "eligible": eligible,
            "preference": state,
        }

    def recompute_preference(self, subject_key: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        reference = now or datetime.now(UTC)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT value, weight, observed_at, category, signal_type, evidence_class
                FROM user_signals
                WHERE subject_key = ? AND eligible = 1
                ORDER BY observed_at ASC
                """,
                (subject_key,),
            ).fetchall()
        if not rows:
            return None

        signals: list[dict[str, Any]] = []
        for row in rows:
            try:
                observed = datetime.fromisoformat(str(row["observed_at"]).replace("Z", "+00:00"))
            except ValueError:
                continue
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=UTC)
            age_days = max(0.0, (reference - observed.astimezone(UTC)).total_seconds() / 86400.0)
            signals.append({**dict(row), "observed": observed.astimezone(UTC), "age_days": age_days})
        if not signals:
            return None

        def window(days_min: float, days_max: float) -> list[dict[str, Any]]:
            return [signal for signal in signals if days_min <= signal["age_days"] < days_max]

        def weighted_average(items: list[dict[str, Any]]) -> float | None:
            denominator = sum(float(item["weight"]) for item in items)
            if denominator <= 0:
                return None
            return sum(float(item["value"]) * float(item["weight"]) for item in items) / denominator

        decayed_weights = [float(signal["weight"]) * math.exp(-signal["age_days"] / 60.0) for signal in signals]
        denominator = sum(decayed_weights)
        raw_current = (
            sum(float(signal["value"]) * weight for signal, weight in zip(signals, decayed_weights)) / denominator
            if denominator > 0
            else 0.0
        )
        days_since_latest = min(signal["age_days"] for signal in signals)
        freshness = math.exp(-days_since_latest / 90.0)
        current_score = max(-1.0, min(1.0, raw_current * freshness))
        recent_items = window(0, 30)
        prior_items = window(30, 180)
        long_items = window(0, 3650)
        recent = weighted_average(recent_items)
        prior = weighted_average(prior_items)
        long_term = weighted_average(long_items)
        historical_peak = max(float(signal["value"]) for signal in signals)
        meaningful = [signal for signal in signals if float(signal["value"]) >= 0.35]
        last_meaningful = max((signal["observed"] for signal in meaningful), default=None)
        days_since_meaningful = (
            max(0.0, (reference - last_meaningful).total_seconds() / 86400.0)
            if last_meaningful is not None
            else float("inf")
        )

        comparison_recent = recent if recent is not None else 0.0
        comparison_prior = prior if prior is not None else historical_peak
        delta = comparison_recent - comparison_prior
        if delta >= 0.15:
            trend = "rising"
        elif delta <= -0.15 or (days_since_meaningful > 30 and historical_peak >= 0.5):
            trend = "falling"
        else:
            trend = "stable"

        if current_score <= -0.3:
            lifecycle = "rejected"
        elif historical_peak >= 0.5 and days_since_latest > 90:
            lifecycle = "dormant"
        elif historical_peak >= 0.55 and (
            current_score <= historical_peak - 0.2 or trend == "falling"
        ):
            lifecycle = "waning"
        elif current_score >= 0.55 and days_since_latest <= 30:
            lifecycle = "active"
        else:
            lifecycle = "occasional"

        confidence = max(0.0, min(1.0, (1.0 - math.exp(-len(signals) / 5.0)) * freshness))
        category = str(signals[-1]["category"])
        windows = {
            "recent_30d": {"average": recent, "count": len(recent_items)},
            "prior_30_to_180d": {"average": prior, "count": len(prior_items)},
            "long_term": {"average": long_term, "count": len(long_items)},
            "days_since_latest": round(days_since_latest, 3),
            "days_since_meaningful": None if math.isinf(days_since_meaningful) else round(days_since_meaningful, 3),
        }
        state_id = _stable_id("pref", subject_key)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO preference_states (
                    id, subject_key, entity_id, category, current_score, trend,
                    lifecycle, confidence, historical_peak, windows_json,
                    evidence_count, last_meaningful_engagement, updated_at
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject_key) DO UPDATE SET
                    category = excluded.category,
                    current_score = excluded.current_score,
                    trend = excluded.trend,
                    lifecycle = excluded.lifecycle,
                    confidence = excluded.confidence,
                    historical_peak = excluded.historical_peak,
                    windows_json = excluded.windows_json,
                    evidence_count = excluded.evidence_count,
                    last_meaningful_engagement = excluded.last_meaningful_engagement,
                    updated_at = excluded.updated_at
                """,
                (
                    state_id,
                    subject_key,
                    category,
                    current_score,
                    trend,
                    lifecycle,
                    confidence,
                    historical_peak,
                    _json(windows),
                    len(signals),
                    last_meaningful.isoformat() if last_meaningful is not None else "",
                    _now(),
                ),
            )
        return self.get_preference(subject_key)

    def get_preference(self, subject_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM preference_states WHERE subject_key = ?",
                (subject_key,),
            ).fetchone()
        return self._preference_row(row) if row is not None else None

    def list_preferences(self, *, category: str = "", limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if category:
            where = "WHERE category = ?"
            params.append(category)
        params.append(max(1, min(int(limit), 500)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM preference_states {where} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._preference_row(row) for row in rows]

    @staticmethod
    def _preference_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["windows"] = json.loads(str(item.pop("windows_json") or "{}"))
        return item

    def start_ingestion_job(self, item: IngestionJobInput) -> dict[str, Any]:
        scoped_key = _stable_id("idem", item.connector, item.account_id, item.idempotency_key)
        job_id = _stable_id("job", scoped_key)
        now = _now()
        lease_expires_at = (datetime.now(UTC) + timedelta(seconds=item.lease_seconds)).isoformat()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM ingestion_jobs WHERE idempotency_key = ?",
                (scoped_key,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO ingestion_jobs (
                        id, connector, account_id, job_type, status, idempotency_key,
                        requested_by, stats_json, created_at, started_at,
                        attempt_count, lease_expires_at
                    ) VALUES (?, ?, ?, ?, 'running', ?, ?, '{}', ?, ?, 1, ?)
                    """,
                    (
                        job_id,
                        item.connector,
                        item.account_id,
                        item.job_type,
                        scoped_key,
                        item.requested_by,
                        now,
                        now,
                        lease_expires_at,
                    ),
                )
                row = connection.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
                return {**self._job_row(row), "created": True, "should_run": True}
            existing_status = str(existing["status"])
            lease_expired = existing_status == "running" and self._timestamp_expired(
                str(existing["lease_expires_at"] or ""),
                datetime.now(UTC),
            )
            if existing_status == "failed" or lease_expired:
                connection.execute(
                    """
                    UPDATE ingestion_jobs
                    SET status = 'running', requested_by = ?, stats_json = '{}',
                        error_code = '', started_at = ?, completed_at = '',
                        attempt_count = attempt_count + 1, lease_expires_at = ?
                    WHERE id = ?
                    """,
                    (item.requested_by, now, lease_expires_at, str(existing["id"])),
                )
                retried = connection.execute(
                    "SELECT * FROM ingestion_jobs WHERE id = ?",
                    (str(existing["id"]),),
                ).fetchone()
                return {
                    **self._job_row(retried),
                    "created": False,
                    "should_run": True,
                    "retried": True,
                    "reclaimed": lease_expired,
                }
            row = self._job_row(existing)
            return {
                **row,
                "created": False,
                "should_run": False,
                "deduplicated": True,
            }

    def complete_ingestion_job(
        self,
        job_id: str,
        *,
        stats: dict[str, Any] | None = None,
        cursor: SyncCursorInput | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown ingestion job: {job_id}")
            if str(row["status"]) == "completed":
                return self._job_row(row)
            if str(row["status"]) != "running":
                raise ValueError(f"Cannot complete ingestion job in {row['status']} state.")
            if cursor is not None:
                self._upsert_sync_cursor(connection, cursor, succeeded_at=now)
            connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'completed', stats_json = ?, error_code = '',
                    completed_at = ?, lease_expires_at = ''
                WHERE id = ?
                """,
                (_json(stats or {}), now, job_id),
            )
            completed = connection.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_row(completed)

    def fail_ingestion_job(self, job_id: str, *, error_code: str) -> dict[str, Any]:
        safe_code = "".join(character for character in error_code.upper() if character.isalnum() or character == "_")[:80]
        safe_code = safe_code or "INGESTION_FAILED"
        now = _now()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown ingestion job: {job_id}")
            if str(row["status"]) == "completed":
                raise ValueError("Completed ingestion jobs cannot be failed.")
            self._record_cursor_failure(
                connection,
                connector=str(row["connector"]),
                account_id=str(row["account_id"]),
                error_code=safe_code,
                failed_at=now,
            )
            connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'failed', error_code = ?, completed_at = ?,
                    lease_expires_at = ''
                WHERE id = ?
                """,
                (safe_code, now, job_id),
            )
            failed = connection.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_row(failed)

    def get_sync_cursor(self, connector: str, account_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sync_cursors WHERE connector = ? AND account_id = ?",
                (connector, account_id),
            ).fetchone()
        return self._cursor_row(row) if row is not None else None

    def list_sync_cursors(self, *, connector: str = "", limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if connector:
            where = "WHERE connector = ?"
            params.append(connector)
        params.append(max(1, min(int(limit), 500)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM sync_cursors {where} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._cursor_row(row) for row in rows]

    def list_ingestion_jobs(self, *, connector: str = "", limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if connector:
            where = "WHERE connector = ?"
            params.append(connector)
        params.append(max(1, min(int(limit), 500)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM ingestion_jobs {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._job_row(row) for row in rows]

    def heartbeat_ingestion_job(self, job_id: str, *, lease_seconds: int = 900) -> dict[str, Any]:
        bounded_lease = max(30, min(int(lease_seconds), 86400))
        lease_expires_at = (datetime.now(UTC) + timedelta(seconds=bounded_lease)).isoformat()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown ingestion job: {job_id}")
            if str(row["status"]) != "running":
                raise ValueError("Only running ingestion jobs can renew a lease.")
            connection.execute(
                "UPDATE ingestion_jobs SET lease_expires_at = ? WHERE id = ?",
                (lease_expires_at, job_id),
            )
            renewed = connection.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_row(renewed)

    @staticmethod
    def _upsert_sync_cursor(
        connection: sqlite3.Connection,
        item: SyncCursorInput,
        *,
        succeeded_at: str,
    ) -> None:
        cursor_id = _stable_id("cur", item.connector, item.account_id)
        connection.execute(
            """
            INSERT INTO sync_cursors (
                id, connector, account_id, cursor, state_json,
                last_success_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(connector, account_id) DO UPDATE SET
                cursor = excluded.cursor,
                state_json = excluded.state_json,
                last_success_at = excluded.last_success_at,
                last_error_at = '',
                last_error_code = '',
                updated_at = excluded.updated_at
            """,
            (
                cursor_id,
                item.connector,
                item.account_id,
                item.cursor,
                _json(item.state),
                succeeded_at,
                succeeded_at,
            ),
        )

    @staticmethod
    def _record_cursor_failure(
        connection: sqlite3.Connection,
        *,
        connector: str,
        account_id: str,
        error_code: str,
        failed_at: str,
    ) -> None:
        cursor_id = _stable_id("cur", connector, account_id)
        connection.execute(
            """
            INSERT INTO sync_cursors (
                id, connector, account_id, cursor, state_json,
                last_error_at, last_error_code, updated_at
            ) VALUES (?, ?, ?, '', '{}', ?, ?, ?)
            ON CONFLICT(connector, account_id) DO UPDATE SET
                last_error_at = excluded.last_error_at,
                last_error_code = excluded.last_error_code,
                updated_at = excluded.updated_at
            """,
            (cursor_id, connector, account_id, failed_at, error_code, failed_at),
        )

    @staticmethod
    def _job_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["stats"] = json.loads(str(item.pop("stats_json") or "{}"))
        return item

    @staticmethod
    def _cursor_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["state"] = json.loads(str(item.pop("state_json") or "{}"))
        return item

    @staticmethod
    def _timestamp_expired(value: str, reference: datetime) -> bool:
        if not value:
            return True
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return True
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC) <= reference.astimezone(UTC)

    def list_sources(self, *, kind: str = "", limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if kind:
            where = "WHERE kind = ?"
            params.append(kind)
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, kind, external_id, account_id, title, uri, source_path,
                       sensitivity, external_policy, trust, status, current_version_id,
                       first_seen_at, last_seen_at, updated_at
                FROM sources {where}
                ORDER BY updated_at DESC LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_observations(self, *, origin: str = "", limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if origin:
            where = "WHERE origin = ?"
            params.append(origin)
        params.append(max(1, min(int(limit), 500)))
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, event_key, origin, actor, trigger, action, source_id,
                       sensitivity, confidence, observed_at, expires_at, promotion_status
                FROM observations {where}
                ORDER BY observed_at DESC LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def create_context_pack(self, request: ContextPackRequest) -> dict[str, Any]:
        terms = [term.casefold() for term in request.query.split() if len(term) > 2][:12]
        sources = self.list_sources(limit=250)
        if request.source_kinds:
            allowed_kinds = {kind.casefold() for kind in request.source_kinds}
            sources = [source for source in sources if str(source["kind"]).casefold() in allowed_kinds]
        if terms:
            sources = [
                source
                for source in sources
                if any(term in f"{source.get('title', '')} {source.get('external_id', '')}".casefold() for term in terms)
            ]
        evidence: list[dict[str, Any]] = []
        scrubber = PrivacyScrubber()
        with self._connect() as connection:
            for source in sources[:20]:
                version = connection.execute(
                    "SELECT content_hash, blob_path, observed_at, published_at FROM source_versions WHERE id = ?",
                    (source.get("current_version_id"),),
                ).fetchone()
                if version is None:
                    continue
                title = str(source["title"] or "")
                uri = str(source["uri"] or "")
                if request.destination == "external":
                    title, _replacements = scrubber.scrub_regex(title)
                    if source["sensitivity"] != "public" or source["external_policy"] != "allow":
                        uri = ""
                record = {
                    "source_id": source["id"],
                    "kind": source["kind"],
                    "title": title,
                    "uri": uri,
                    "content_hash": version["content_hash"],
                    "observed_at": version["observed_at"],
                    "published_at": version["published_at"],
                    "sensitivity": source["sensitivity"],
                    "external_policy": source["external_policy"],
                }
                raw_allowed = (
                    request.destination == "local"
                    and request.include_raw_content
                    and bool(version["blob_path"])
                )
                if raw_allowed:
                    record["content"] = self.blobs.read_text(str(version["blob_path"]))
                elif request.destination == "external" and source["external_policy"] == "deny_raw":
                    record["content_withheld"] = True
                evidence.append(record)

        pack_id = _stable_id("ctx", request.purpose, request.destination, _now(), request.query)
        policy = {
            "raw_private_content": "withheld" if request.destination == "external" else "local_only",
            "citations_required": request.citations_required,
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO context_packs (
                    id, purpose, destination, query_hash, query_text, token_budget,
                    citations_required, evidence_json, policy_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pack_id,
                    request.purpose,
                    request.destination,
                    _content_hash(request.query.encode("utf-8")),
                    request.query,
                    request.token_budget,
                    int(request.citations_required),
                    _json(evidence),
                    _json(policy),
                    _now(),
                ),
            )
        return {
            "id": pack_id,
            "purpose": request.purpose,
            "destination": request.destination,
            "token_budget": request.token_budget,
            "citations_required": request.citations_required,
            "evidence": evidence,
            "policy": policy,
        }

    def status(self) -> dict[str, Any]:
        tables = (
            "sources",
            "source_versions",
            "entities",
            "relationships",
            "observations",
            "claims",
            "user_signals",
            "preference_states",
            "derived_insights",
            "projections",
            "sync_cursors",
            "ingestion_jobs",
            "context_packs",
        )
        with self._connect() as connection:
            counts = {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        return {
            "ready": True,
            "schema_version": version,
            "storage": "embedded_sqlite",
            "blobs": "local_content_addressed_gzip",
            "counts": counts,
        }
