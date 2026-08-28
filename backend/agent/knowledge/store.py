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
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
from typing import Any, Iterable

from agent.knowledge.models import (
    BookUserLearningCandidateInput,
    BookUserLearningEvidenceReference,
    BookWisdomEvidenceReference,
    BookWisdomRecordInput,
    ContentAnnotationInput,
    ContextPackRequest,
    EntityIdentityInput,
    IngestionJobInput,
    ObservationActor,
    ObservationInput,
    ProjectionInput,
    SourceItemInput,
    SyncCursorInput,
    UserSignalInput,
)
from agent.privacy.scrubber import PrivacyScrubber


SCHEMA_VERSION = 14


class IngestionJobLeaseLost(RuntimeError):
    """The caller no longer owns this ingestion attempt."""


class BookDiscoveryCandidateChanged(RuntimeError):
    """The candidate changed while a verification attempt was in flight."""


_SENSITIVE_LABELS = {
    "harassment",
    "hate_or_protected_class",
    "politics",
    "sexual_content",
    "self_harm",
    "violence",
    "health",
    "financial",
    "ambiguous_engagement",
}

_EVIDENCE_WEIGHT_CAPS = {
    "explicit": 10.0,
    "engagement": 2.0,
    "imported": 1.0,
    "passive": 0.25,
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    try:
        result = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _book_receipt_metadata(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "byte_size",
        "policy_version",
        "limits",
        "scanner",
        "scanner_version",
        "scan_outcome",
        "parser_version",
        "schema_version",
        "resource_count",
        "spine_item_count",
        "block_count",
        "navigation_item_count",
        "quality_outcome",
        "quality_evaluated",
        "compiler_version",
        "model_version",
        "prompt_version",
        "embedding_model",
        "embedding_model_revision",
        "index_collection",
        "index_count",
        "chunk_count",
        "citation_count",
        "embedding_count",
    }
    if set(value) - allowed:
        raise ValueError("Unsupported Book receipt metadata.")
    clean: dict[str, Any] = {}
    if "byte_size" in value:
        clean["byte_size"] = max(0, int(value["byte_size"]))
    if "policy_version" in value:
        policy_version = str(value["policy_version"] or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", policy_version):
            raise ValueError("Invalid Book policy version.")
        clean["policy_version"] = policy_version
    if "limits" in value:
        limits = dict(value["limits"] or {})
        expected = {
            "max_asset_bytes",
            "max_entries",
            "max_expanded_bytes",
            "max_compression_ratio",
        }
        if set(limits) != expected:
            raise ValueError("Invalid Book receipt limits.")
        clean["limits"] = {
            "max_asset_bytes": max(0, int(limits["max_asset_bytes"])),
            "max_entries": max(0, int(limits["max_entries"])),
            "max_expanded_bytes": max(0, int(limits["max_expanded_bytes"])),
            "max_compression_ratio": max(0.0, float(limits["max_compression_ratio"])),
        }
    for key in ("scanner", "scanner_version"):
        if key in value:
            label = str(value[key] or "").strip()
            if len(label) > 120 or not all(character.isalnum() or character in "._ -" for character in label):
                raise ValueError("Invalid Book scanner metadata.")
            clean[key] = label
    if "scan_outcome" in value:
        outcome = str(value["scan_outcome"] or "")
        if outcome not in {"clean", "detected", "unavailable", "error"}:
            raise ValueError("Invalid Book scan outcome.")
        clean["scan_outcome"] = outcome
    for key in (
        "parser_version",
        "schema_version",
        "compiler_version",
        "model_version",
        "prompt_version",
        "embedding_model",
        "embedding_model_revision",
        "index_collection",
    ):
        if key in value:
            label = str(value[key] or "").strip()
            if (
                not re.fullmatch(r"[A-Za-z0-9._:/-]{1,200}", label)
                or label.startswith("/")
                or ".." in label
                or "//" in label
                or re.match(r"^[A-Za-z]:/", label)
            ):
                raise ValueError("Invalid Book processing version.")
            clean[key] = label
    for key in (
        "resource_count",
        "spine_item_count",
        "block_count",
        "navigation_item_count",
        "index_count",
        "chunk_count",
        "citation_count",
        "embedding_count",
    ):
        if key in value:
            clean[key] = max(0, int(value[key]))
    if "quality_outcome" in value:
        outcome = str(value["quality_outcome"] or "")
        if outcome not in {
            "PASS",
            "DEGRADED",
            "OCR_REQUIRED",
            "FAILED_RETRYABLE",
            "FAILED_PERMANENT",
        }:
            raise ValueError("Invalid Book quality outcome.")
        clean["quality_outcome"] = outcome
    if "quality_evaluated" in value:
        clean["quality_evaluated"] = bool(value["quality_evaluated"])
    return clean


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalized_proposition(value: str) -> str:
    return " ".join(value.casefold().split())


@dataclass(frozen=True)
class BookDocumentResourcePublication:
    id: str
    manifest_id: str
    resource_path: str
    media_type: str
    source_digest: str
    extracted_digest: str
    artifact_digest: str
    blob_path: str
    byte_size: int
    artifact_byte_size: int
    spine_position: int | None
    disposition: str
    reason_code: str


@dataclass(frozen=True)
class BookDocumentPublication:
    user_id: str
    import_id: str
    run_id: str
    document_id: str
    asset_id: str
    input_digest: str
    document_digest: str
    document_blob_path: str
    parser_version: str
    schema_version: str
    quality_outcome: str
    quality_evaluated: bool
    resources: tuple[BookDocumentResourcePublication, ...]
    receipt_metadata: dict[str, Any]


@dataclass(frozen=True)
class BookQualityAssessmentPublication:
    assessment_id: str
    user_id: str
    import_id: str
    run_id: str
    document_id: str
    document_digest: str
    policy_version: str
    policy_snapshot_hash: str
    outcome: str
    report_digest: str
    report_blob_path: str


@dataclass(frozen=True)
class BookMaterializationPublication:
    materialization_id: str
    user_id: str
    import_id: str
    run_id: str
    edition_id: str
    document_id: str
    document_digest: str
    quality_assessment_id: str
    schema_version: str
    compiler_version: str
    model_version: str
    prompt_version: str
    embedding_model: str
    embedding_model_revision: str
    policy_snapshot_hash: str
    bundle_digest: str
    bundle_blob_path: str
    skill_id: str
    skill_version: str
    index_collection: str
    index_count: int
    artifact_paths: tuple[str, ...]
    chunk_count: int
    citation_count: int
    embedding_count: int


def _build_preference_state(
    subject_key: str,
    rows: Iterable[sqlite3.Row],
    reference: datetime,
) -> dict[str, Any] | None:
    signals: list[dict[str, Any]] = []
    for row in rows:
        observed = _parse_datetime(row["observed_at"])
        if observed is None:
            continue
        age_days = max(0.0, (reference - observed).total_seconds() / 86400.0)
        signals.append({**dict(row), "observed": observed, "age_days": age_days})
    if not signals:
        return None

    def window(days_min: float, days_max: float) -> list[dict[str, Any]]:
        return [signal for signal in signals if days_min <= signal["age_days"] < days_max]

    def weighted_average(items: list[dict[str, Any]]) -> float | None:
        denominator = sum(float(item["weight"]) for item in items)
        if denominator <= 0:
            return None
        return sum(float(item["value"]) * float(item["weight"]) for item in items) / denominator

    decayed_weights = [
        float(signal["weight"]) * math.exp(-signal["age_days"] / 60.0)
        for signal in signals
    ]
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

    category = str(signals[-1]["category"])
    comparison_recent = recent if recent is not None else 0.0
    comparison_prior = prior if prior is not None else historical_peak
    delta = comparison_recent - comparison_prior
    recent_positive = sum(1 for item in recent_items if float(item["value"]) >= 0.35)
    prior_positive = sum(1 for item in prior_items if float(item["value"]) >= 0.35)
    prior_rate_per_30d = prior_positive / 5.0
    volume_falling = (
        category in {"youtube_channel", "youtube_search_theme"}
        and prior_positive >= 5
        and recent_positive <= prior_rate_per_30d * 0.5
    )
    volume_rising = (
        category in {"youtube_channel", "youtube_search_theme"}
        and prior_positive >= 5
        and recent_positive >= max(3.0, prior_rate_per_30d * 1.5)
    )
    if delta >= 0.15 or volume_rising:
        trend = "rising"
    elif delta <= -0.15 or volume_falling or (days_since_meaningful > 30 and historical_peak >= 0.5):
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
    return {
        "subject_key": subject_key,
        "category": category,
        "current_score": current_score,
        "trend": trend,
        "lifecycle": lifecycle,
        "confidence": confidence,
        "historical_peak": historical_peak,
        "windows": {
            "recent_30d": {"average": recent, "count": len(recent_items)},
            "prior_30_to_180d": {"average": prior, "count": len(prior_items)},
            "long_term": {"average": long_term, "count": len(long_items)},
            "days_since_latest": round(days_since_latest, 3),
            "days_since_meaningful": (
                None if math.isinf(days_since_meaningful) else round(days_since_meaningful, 3)
            ),
        },
        "evidence_count": len(signals),
        "last_meaningful_engagement": (
            last_meaningful.isoformat() if last_meaningful is not None else ""
        ),
    }


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

    def put_book_asset(self, content: bytes, *, tenant_scope: str) -> tuple[str, str, int]:
        if not re.fullmatch(r"[a-z0-9_]{8,80}", tenant_scope):
            raise ValueError("Invalid tenant blob scope.")
        digest = _content_hash(content)
        relative = Path("books") / "quarantine" / tenant_scope / digest[:2] / f"{digest}.epub"
        self._put_raw(content, relative=relative, digest=digest)
        return digest, relative.as_posix(), len(content)

    def put_book_artifact(
        self,
        content: bytes,
        *,
        tenant_scope: str,
        category: str,
        suffix: str,
    ) -> tuple[str, str, int]:
        if not re.fullmatch(r"[a-z0-9_]{8,80}", tenant_scope):
            raise ValueError("Invalid tenant blob scope.")
        if category not in {"resources", "documents", "quality", "materialization"} or suffix not in {
            "json",
            "md",
            "txt",
        }:
            raise ValueError("Invalid Book artifact path.")
        raw = bytes(content)
        digest = _content_hash(raw)
        relative = (
            Path("books")
            / "artifacts"
            / tenant_scope
            / category
            / digest[:2]
            / f"{digest}.{suffix}"
        )
        self._put_raw(raw, relative=relative, digest=digest)
        return digest, relative.as_posix(), len(raw)

    def _put_raw(self, content: bytes, *, relative: Path, digest: str) -> None:
        target = self.root / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            handle, temp_name = tempfile.mkstemp(prefix=f".{digest}.", suffix=".tmp", dir=target.parent)
            try:
                with os.fdopen(handle, "wb") as output:
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                try:
                    os.replace(temp_name, target)
                except PermissionError:
                    # Windows can deny replacement while a concurrent publisher reads the same blob.
                    if not target.is_file() or target.read_bytes() != content:
                        raise
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)

    def read_book_artifact(self, relative_path: str) -> bytes:
        target = self.resolve(relative_path)
        return target.read_bytes()

    def resolve(self, relative_path: str) -> Path:
        target = (self.root / relative_path).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError("Blob path escapes the knowledge store.")
        return target


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
        with closing(self._connect()) as connection, connection:
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
                version = 3
            if version < 4:
                self._migrate_v4(connection)
                connection.execute("PRAGMA user_version = 4")
                version = 4
            if version < 5:
                self._migrate_v5(connection)
                connection.execute("PRAGMA user_version = 5")
                version = 5
            if version < 6:
                self._migrate_v6(connection)
                connection.execute("PRAGMA user_version = 6")
                version = 6
            if version < 7:
                self._migrate_v7(connection)
                connection.execute("PRAGMA user_version = 7")
                version = 7
            if version < 8:
                self._migrate_v8(connection)
                connection.execute("PRAGMA user_version = 8")
                version = 8
            if version < 9:
                self._migrate_v9(connection)
                connection.execute("PRAGMA user_version = 9")
                version = 9
            if version < 10:
                self._migrate_v10(connection)
                connection.execute("PRAGMA user_version = 10")
                version = 10
            if version < 11:
                self._migrate_v11(connection)
                connection.execute("PRAGMA user_version = 11")
                version = 11
            if version < 12:
                self._migrate_v12(connection)
                connection.execute("PRAGMA user_version = 12")
                version = 12
            if version < 13:
                self._migrate_v13(connection)
                version = 13
            if version < 14:
                self._migrate_v14(connection)

    @staticmethod
    def _migrate_v13(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS book_discovery_candidates (
                id TEXT PRIMARY KEY,
                tenant_scope TEXT NOT NULL,
                objective TEXT NOT NULL CHECK(objective IN ('user_discovery', 'vellum_exploration')),
                work_id TEXT NOT NULL,
                identity_hash TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('discovered', 'dismissed', 'expired')),
                metadata_json TEXT NOT NULL,
                relevance_score REAL NOT NULL,
                job_id TEXT NOT NULL REFERENCES ingestion_jobs(id),
                discovered_at TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                UNIQUE(tenant_scope, objective, work_id),
                UNIQUE(tenant_scope, objective, identity_hash)
            );
            CREATE INDEX IF NOT EXISTS book_discovery_scope_state
                ON book_discovery_candidates(tenant_scope, state, objective);
            PRAGMA user_version = 13;
            COMMIT;
            """
        )

    @staticmethod
    def _migrate_v14(connection: sqlite3.Connection) -> None:
        table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'book_discovery_candidates'"
        ).fetchone()
        if table is not None and "verified" in str(table[0] or "").casefold():
            connection.execute(
                "CREATE INDEX IF NOT EXISTS book_discovery_scope_state "
                "ON book_discovery_candidates(tenant_scope, state, objective)"
            )
            connection.execute("PRAGMA user_version = 14")
            return
        if table is None:
            connection.execute(
                """
                CREATE TABLE book_discovery_candidates (
                    id TEXT PRIMARY KEY,
                    tenant_scope TEXT NOT NULL,
                    objective TEXT NOT NULL CHECK(objective IN ('user_discovery', 'vellum_exploration')),
                    work_id TEXT NOT NULL,
                    identity_hash TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('discovered', 'verified', 'dismissed', 'expired')),
                    metadata_json TEXT NOT NULL,
                    relevance_score REAL NOT NULL,
                    job_id TEXT NOT NULL REFERENCES ingestion_jobs(id),
                    discovered_at TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    UNIQUE(tenant_scope, objective, work_id),
                    UNIQUE(tenant_scope, objective, identity_hash)
                )
                """
            )
            connection.execute(
                "CREATE INDEX book_discovery_scope_state "
                "ON book_discovery_candidates(tenant_scope, state, objective)"
            )
            connection.execute("PRAGMA user_version = 14")
            return

        # SQLite cannot alter a CHECK constraint. Keep the copy and rename in
        # one transaction so an interrupted migration leaves the v13 table.
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("DROP TABLE IF EXISTS book_discovery_candidates_v14")
            connection.execute(
                """
                CREATE TABLE book_discovery_candidates_v14 (
                    id TEXT PRIMARY KEY,
                    tenant_scope TEXT NOT NULL,
                    objective TEXT NOT NULL CHECK(objective IN ('user_discovery', 'vellum_exploration')),
                    work_id TEXT NOT NULL,
                    identity_hash TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('discovered', 'verified', 'dismissed', 'expired')),
                    metadata_json TEXT NOT NULL,
                    relevance_score REAL NOT NULL,
                    job_id TEXT NOT NULL REFERENCES ingestion_jobs(id),
                    discovered_at TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    UNIQUE(tenant_scope, objective, work_id),
                    UNIQUE(tenant_scope, objective, identity_hash)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO book_discovery_candidates_v14 (
                    id, tenant_scope, objective, work_id, identity_hash, state,
                    metadata_json, relevance_score, job_id, discovered_at, checked_at, expires_at
                )
                SELECT id, tenant_scope, objective, work_id, identity_hash, state,
                       metadata_json, relevance_score, job_id, discovered_at, checked_at, expires_at
                FROM book_discovery_candidates
                """
            )
            connection.execute("DROP TABLE book_discovery_candidates")
            connection.execute(
                "ALTER TABLE book_discovery_candidates_v14 RENAME TO book_discovery_candidates"
            )
            connection.execute(
                "CREATE INDEX book_discovery_scope_state "
                "ON book_discovery_candidates(tenant_scope, state, objective)"
            )
            connection.execute("PRAGMA user_version = 14")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

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
            CREATE INDEX observations_origin_action_idx ON observations(origin, action);

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

    @staticmethod
    def _migrate_v4(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS content_annotations (
                id TEXT PRIMARY KEY,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                taxonomy_version TEXT NOT NULL,
                labels_json TEXT NOT NULL DEFAULT '[]',
                context TEXT NOT NULL DEFAULT '',
                stance TEXT NOT NULL DEFAULT 'unknown',
                intent TEXT NOT NULL DEFAULT 'unknown',
                confidence REAL NOT NULL DEFAULT 0,
                eligible_for_preference INTEGER NOT NULL DEFAULT 0,
                eligible_for_style INTEGER NOT NULL DEFAULT 0,
                requires_review INTEGER NOT NULL DEFAULT 1,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(target_type, target_id, taxonomy_version)
            );
            CREATE INDEX IF NOT EXISTS content_annotations_target
            ON content_annotations(target_type, target_id);
            CREATE INDEX IF NOT EXISTS content_annotations_review
            ON content_annotations(requires_review, updated_at DESC);
            """
        )

    @staticmethod
    def _migrate_v5(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE INDEX IF NOT EXISTS observations_origin_action_idx "
            "ON observations(origin, action)"
        )

    @staticmethod
    def _migrate_v6(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS book_assets (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                blob_path TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, sha256)
            );
            CREATE TABLE IF NOT EXISTS user_book_imports (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                asset_id TEXT NOT NULL REFERENCES book_assets(id) ON DELETE RESTRICT,
                rights_attestation_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, asset_id)
            );
            CREATE TABLE IF NOT EXISTS book_ingestion_runs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                asset_id TEXT NOT NULL REFERENCES book_assets(id) ON DELETE RESTRICT,
                pipeline_version TEXT NOT NULL,
                policy_snapshot_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                current_stage TEXT NOT NULL,
                error_code TEXT NOT NULL DEFAULT '',
                attempt_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, asset_id, pipeline_version, policy_snapshot_hash)
            );
            CREATE TABLE IF NOT EXISTS book_stage_receipts (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES book_ingestion_runs(id) ON DELETE CASCADE,
                stage TEXT NOT NULL,
                stage_version TEXT NOT NULL,
                input_digest TEXT NOT NULL,
                output_digest TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                reason_code TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(run_id, stage, stage_version, input_digest, attempt)
            );
            CREATE INDEX IF NOT EXISTS book_imports_user_time
            ON user_book_imports(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS book_runs_asset_time
            ON book_ingestion_runs(asset_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS book_receipts_run_time
            ON book_stage_receipts(run_id, created_at ASC);
            """
        )

    @staticmethod
    def _migrate_v7(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS book_documents (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                run_id TEXT NOT NULL REFERENCES book_ingestion_runs(id) ON DELETE CASCADE,
                asset_id TEXT NOT NULL REFERENCES book_assets(id) ON DELETE RESTRICT,
                schema_version TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                input_digest TEXT NOT NULL,
                digest TEXT NOT NULL,
                blob_path TEXT NOT NULL,
                quality_outcome TEXT NOT NULL,
                quality_evaluated INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(id, user_id),
                UNIQUE(user_id, run_id)
            );
            CREATE TABLE IF NOT EXISTS book_document_resources (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                manifest_id TEXT NOT NULL,
                resource_path TEXT NOT NULL,
                media_type TEXT NOT NULL,
                source_digest TEXT NOT NULL,
                extracted_digest TEXT NOT NULL,
                artifact_digest TEXT NOT NULL,
                blob_path TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                artifact_byte_size INTEGER NOT NULL,
                spine_position INTEGER,
                disposition TEXT NOT NULL,
                reason_code TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(document_id, manifest_id),
                CHECK(disposition IN ('included', 'excluded')),
                CHECK(
                    (disposition = 'included' AND artifact_digest <> '' AND blob_path <> '')
                    OR (disposition = 'excluded' AND artifact_digest = '' AND blob_path = '')
                ),
                FOREIGN KEY(document_id, user_id) REFERENCES book_documents(id, user_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS book_documents_run_time
            ON book_documents(run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS book_document_resources_document_position
            ON book_document_resources(document_id, spine_position ASC, resource_path ASC);
            CREATE UNIQUE INDEX IF NOT EXISTS book_document_successful_stage_key
            ON book_stage_receipts(run_id, stage, stage_version, input_digest)
            WHERE status = 'succeeded' AND stage IN ('extracted', 'identified', 'structured');
            """
        )

    @staticmethod
    def _migrate_v10(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(user_book_imports)").fetchall()
        }
        if "local_only" not in columns:
            connection.execute(
                "ALTER TABLE user_book_imports ADD COLUMN local_only INTEGER NOT NULL DEFAULT 0"
            )
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS book_retrieval_receipts (
                id TEXT PRIMARY KEY,
                tenant_scope TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                destination TEXT NOT NULL,
                active_count INTEGER NOT NULL,
                candidate_count INTEGER NOT NULL,
                evidence_count INTEGER NOT NULL,
                token_budget INTEGER NOT NULL,
                tokens_used INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS book_retrieval_receipts_tenant_time
            ON book_retrieval_receipts(tenant_scope, created_at DESC);
            """
        )

    @staticmethod
    def _migrate_v11(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_learning_candidates (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                dedupe_key TEXT NOT NULL,
                proposition_type TEXT NOT NULL,
                proposition TEXT NOT NULL,
                basis TEXT NOT NULL,
                actor TEXT NOT NULL,
                confidence REAL NOT NULL,
                sensitivity TEXT NOT NULL,
                scope TEXT NOT NULL,
                permitted_uses_json TEXT NOT NULL DEFAULT '[]',
                lifecycle TEXT NOT NULL,
                valid_from TEXT NOT NULL DEFAULT '',
                valid_to TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL DEFAULT '',
                derivation TEXT NOT NULL,
                source_agent TEXT NOT NULL,
                model_version TEXT NOT NULL DEFAULT '',
                prompt_version TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reviewed_at TEXT NOT NULL DEFAULT '',
                confirmed_at TEXT NOT NULL DEFAULT '',
                superseded_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, dedupe_key),
                CHECK(lifecycle IN ('proposed', 'corroborated', 'confirmed', 'disputed', 'superseded', 'rejected', 'expired'))
            );
            CREATE TABLE IF NOT EXISTS user_learning_candidate_evidence (
                id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL REFERENCES user_learning_candidates(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                reference_id TEXT NOT NULL,
                stance TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(candidate_id, kind, reference_id, stance),
                CHECK(kind IN ('observation', 'book', 'book_anchor', 'conversation')),
                CHECK(stance IN ('supports', 'conflicts'))
            );
            CREATE INDEX IF NOT EXISTS user_learning_candidates_user_state_time
            ON user_learning_candidates(user_id, lifecycle, updated_at DESC);
            CREATE INDEX IF NOT EXISTS user_learning_candidate_evidence_candidate
            ON user_learning_candidate_evidence(candidate_id, stance, kind);
            """
        )

    @staticmethod
    def _migrate_v12(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(derived_insights)").fetchall()
        }
        additions = {
            "user_id": "TEXT NOT NULL DEFAULT ''",
            "record_key": "TEXT NOT NULL DEFAULT ''",
            "author_perspective": "TEXT NOT NULL DEFAULT ''",
            "user_perspective": "TEXT NOT NULL DEFAULT ''",
            "vellum_perspective": "TEXT NOT NULL DEFAULT ''",
            "explanation": "TEXT NOT NULL DEFAULT ''",
            "uncertainty_json": "TEXT NOT NULL DEFAULT '[]'",
            "permitted_uses_json": "TEXT NOT NULL DEFAULT '[]'",
            "valid_from": "TEXT NOT NULL DEFAULT ''",
            "valid_to": "TEXT NOT NULL DEFAULT ''",
            "expires_at": "TEXT NOT NULL DEFAULT ''",
            "derivation": "TEXT NOT NULL DEFAULT ''",
            "source_agent": "TEXT NOT NULL DEFAULT ''",
            "model_version": "TEXT NOT NULL DEFAULT ''",
            "prompt_version": "TEXT NOT NULL DEFAULT ''",
            "policy_version": "TEXT NOT NULL DEFAULT ''",
            "schema_version": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE derived_insights ADD COLUMN {name} {definition}")
        connection.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS derived_insights_book_wisdom_key
            ON derived_insights(user_id, record_key)
            WHERE insight_type = 'book_wisdom' AND record_key <> '';
            CREATE TABLE IF NOT EXISTS derived_insight_evidence (
                id TEXT PRIMARY KEY,
                insight_id TEXT NOT NULL REFERENCES derived_insights(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                reference_id TEXT NOT NULL,
                stance TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(insight_id, kind, reference_id, stance),
                CHECK(kind IN ('book', 'book_anchor', 'user_learning_candidate', 'conversation')),
                CHECK(stance IN ('supports', 'conflicts'))
            );
            CREATE INDEX IF NOT EXISTS derived_insight_evidence_insight
            ON derived_insight_evidence(insight_id, stance, kind);
            """
        )

    @staticmethod
    def _migrate_v8(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(book_documents)")
        }
        additions = {
            "quality_assessment_id": "TEXT NOT NULL DEFAULT ''",
            "quality_policy_version": "TEXT NOT NULL DEFAULT ''",
            "quality_policy_snapshot_hash": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in additions.items():
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE book_documents ADD COLUMN {column} {definition}"
                )
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS book_quality_assessments (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                document_digest TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                policy_snapshot_hash TEXT NOT NULL,
                outcome TEXT NOT NULL,
                report_digest TEXT NOT NULL,
                blob_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(document_id, document_digest, policy_version, policy_snapshot_hash),
                CHECK(outcome IN ('PASS', 'DEGRADED', 'OCR_REQUIRED', 'FAILED_RETRYABLE', 'FAILED_PERMANENT')),
                FOREIGN KEY(document_id, user_id) REFERENCES book_documents(id, user_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS book_quality_assessments_document_time
            ON book_quality_assessments(document_id, created_at DESC);
            """
        )

    @staticmethod
    def _migrate_v9(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS book_materializations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                edition_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                document_digest TEXT NOT NULL,
                quality_assessment_id TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                compiler_version TEXT NOT NULL,
                model_version TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding_model_revision TEXT NOT NULL DEFAULT 'default',
                policy_snapshot_hash TEXT NOT NULL,
                bundle_digest TEXT NOT NULL,
                blob_path TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                skill_version TEXT NOT NULL,
                index_collection TEXT NOT NULL DEFAULT 'books',
                index_count INTEGER NOT NULL DEFAULT 0,
                artifact_paths_json TEXT NOT NULL DEFAULT '[]',
                chunk_count INTEGER NOT NULL,
                citation_count INTEGER NOT NULL,
                embedding_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(id, user_id, edition_id),
                FOREIGN KEY(document_id, user_id) REFERENCES book_documents(id, user_id) ON DELETE CASCADE,
                FOREIGN KEY(quality_assessment_id) REFERENCES book_quality_assessments(id) ON DELETE RESTRICT
            );
            CREATE TABLE IF NOT EXISTS active_book_materializations (
                user_id TEXT NOT NULL,
                edition_id TEXT NOT NULL,
                materialization_id TEXT NOT NULL REFERENCES book_materializations(id) ON DELETE RESTRICT,
                activated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, edition_id),
                FOREIGN KEY(materialization_id, user_id, edition_id)
                    REFERENCES book_materializations(id, user_id, edition_id) ON DELETE RESTRICT
            );
            CREATE TABLE IF NOT EXISTS book_materialization_candidates (
                materialization_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                artifact_paths_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS book_materializations_document_time
            ON book_materializations(document_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS book_materializations_edition_time
            ON book_materializations(user_id, edition_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS book_materialization_candidates_time
            ON book_materialization_candidates(updated_at ASC);
            """
        )

    @staticmethod
    def book_import_ids(
        *,
        user_id: str,
        asset_sha256: str,
        pipeline_version: str,
        policy_snapshot_hash: str,
    ) -> dict[str, str]:
        asset_id = _stable_id("bka", user_id, asset_sha256)
        return {
            "asset_id": asset_id,
            "import_id": _stable_id("bki", user_id, asset_id),
            "run_id": _stable_id(
                "bkr",
                user_id,
                asset_id,
                pipeline_version,
                policy_snapshot_hash,
            ),
        }

    @staticmethod
    def book_tenant_scope(user_id: str) -> str:
        return "usr_" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def book_document_id(*, run_id: str, parser_version: str, schema_version: str) -> str:
        return _stable_id("bkd", run_id, parser_version, schema_version)

    @staticmethod
    def book_quality_assessment_id(
        *,
        document_id: str,
        document_digest: str,
        policy_version: str,
        policy_snapshot_hash: str,
    ) -> str:
        return _stable_id(
            "bkq",
            document_id,
            document_digest,
            policy_version,
            policy_snapshot_hash,
        )

    @staticmethod
    def book_materialization_id(
        *,
        user_id: str,
        edition_id: str,
        document_digest: str,
        schema_version: str,
        compiler_version: str,
        model_version: str,
        prompt_version: str,
        embedding_model: str,
        embedding_model_revision: str,
        policy_snapshot_hash: str,
    ) -> str:
        return _stable_id(
            "bkm",
            user_id,
            edition_id,
            document_digest,
            schema_version,
            compiler_version,
            model_version,
            prompt_version,
            embedding_model,
            embedding_model_revision,
            policy_snapshot_hash,
        )

    def begin_book_import(
        self,
        *,
        user_id: str,
        asset_sha256: str,
        byte_size: int,
        rights_attestation_version: str,
        local_only: bool,
        pipeline_version: str,
        policy_snapshot_hash: str,
    ) -> dict[str, Any]:
        identity = self.book_import_ids(
            user_id=user_id,
            asset_sha256=asset_sha256,
            pipeline_version=pipeline_version,
            policy_snapshot_hash=policy_snapshot_hash,
        )
        asset_id = identity["asset_id"]
        import_id = identity["import_id"]
        run_id = identity["run_id"]
        now = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO book_assets (id, user_id, sha256, byte_size, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'received', ?, ?)",
                (asset_id, user_id, asset_sha256, byte_size, now, now),
            )
            connection.execute(
                "INSERT OR IGNORE INTO user_book_imports "
                "(id, user_id, asset_id, rights_attestation_version, local_only, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (import_id, user_id, asset_id, rights_attestation_version, int(local_only), now),
            )
            connection.execute(
                "UPDATE user_book_imports SET local_only = "
                "CASE WHEN local_only = 1 OR ? = 1 THEN 1 ELSE 0 END "
                "WHERE id = ? AND user_id = ?",
                (int(local_only), import_id, user_id),
            )
            existing = connection.execute("SELECT status, attempt_count FROM book_ingestion_runs WHERE id = ?", (run_id,)).fetchone()
            connection.execute(
                "INSERT OR IGNORE INTO book_ingestion_runs (id, user_id, asset_id, pipeline_version, policy_snapshot_hash, status, current_stage, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'received', 'received', ?, ?)",
                (run_id, user_id, asset_id, pipeline_version, policy_snapshot_hash, now, now),
            )
            if existing is not None and str(existing["status"]) == "failed_retryable":
                connection.execute(
                    "UPDATE book_ingestion_runs SET attempt_count = attempt_count + 1, status = 'received', current_stage = 'received', error_code = '', updated_at = ? WHERE id = ?",
                    (now, run_id),
                )
            attempt = int(connection.execute("SELECT attempt_count FROM book_ingestion_runs WHERE id = ?", (run_id,)).fetchone()[0])
            self._record_book_receipt(
                connection,
                run_id=run_id,
                stage="received",
                stage_version="received-v1",
                input_digest=asset_sha256,
                output_digest=asset_sha256,
                status="succeeded",
                attempt=attempt,
                reason_code="RECEIVED",
                metadata={"byte_size": byte_size},
            )
        return self.get_book_import_status(
            user_id=user_id,
            import_id=import_id,
            run_id=run_id,
        )

    def publish_book_stage(
        self,
        *,
        user_id: str,
        import_id: str,
        run_id: str,
        stage: str,
        stage_version: str,
        input_digest: str,
        output_digest: str,
        status: str,
        reason_code: str,
        metadata: dict[str, Any] | None = None,
        blob_path: str = "",
        media_type: str = "",
    ) -> dict[str, Any]:
        now = _now()
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT r.id, r.asset_id, r.attempt_count FROM book_ingestion_runs r JOIN user_book_imports i ON i.asset_id = r.asset_id WHERE i.id = ? AND i.user_id = ? AND r.id = ? LIMIT 1",
                (import_id, user_id, run_id),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown Book import.")
            run_id = str(row["id"])
            attempt = int(row["attempt_count"])
            self._record_book_receipt(
                connection,
                run_id=run_id,
                stage=stage,
                stage_version=stage_version,
                input_digest=input_digest,
                output_digest=output_digest,
                status=status,
                attempt=attempt,
                reason_code=reason_code,
                metadata=metadata or {},
            )
            domain_status = stage if status == "succeeded" else status
            connection.execute(
                "UPDATE book_ingestion_runs SET status = ?, current_stage = ?, error_code = ?, updated_at = ? WHERE id = ?",
                (domain_status, stage, "" if status == "succeeded" else reason_code, now, run_id),
            )
            if blob_path or media_type:
                connection.execute(
                    "UPDATE book_assets SET blob_path = CASE WHEN ? <> '' THEN ? ELSE blob_path END, media_type = CASE WHEN ? <> '' THEN ? ELSE media_type END, status = ?, updated_at = ? WHERE id = ?",
                    (blob_path, blob_path, media_type, media_type, domain_status, now, str(row["asset_id"])),
                )
            else:
                connection.execute(
                    "UPDATE book_assets SET status = ?, updated_at = ? WHERE id = ?",
                    (domain_status, now, str(row["asset_id"])),
                )
        return self.get_book_import_status(
            user_id=user_id,
            import_id=import_id,
            run_id=run_id,
        )

    @staticmethod
    def _record_book_receipt(
        connection: sqlite3.Connection,
        *,
        run_id: str,
        stage: str,
        stage_version: str,
        input_digest: str,
        output_digest: str,
        status: str,
        attempt: int,
        reason_code: str,
        metadata: dict[str, Any],
    ) -> None:
        receipt_id = _stable_id("bks", run_id, stage, stage_version, input_digest, str(attempt))
        connection.execute(
            "INSERT OR IGNORE INTO book_stage_receipts (id, run_id, stage, stage_version, input_digest, output_digest, status, attempt, reason_code, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                receipt_id,
                run_id,
                stage,
                stage_version,
                input_digest,
                output_digest,
                status,
                attempt,
                reason_code,
                _json(_book_receipt_metadata(metadata)),
                _now(),
            ),
        )

    def list_book_library_imports(self, *, user_id: str, limit: int, offset: int) -> tuple[list[str], int]:
        with closing(self._connect()) as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM user_book_imports WHERE user_id = ?", (user_id,),
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT id FROM user_book_imports WHERE user_id = ? "
                "ORDER BY created_at DESC, id ASC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            ).fetchall()
        return [str(row["id"]) for row in rows], int(total)

    def get_book_library_asset(self, *, user_id: str, import_id: str, run_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT a.blob_path, a.byte_size, a.sha256, "
                "EXISTS(SELECT 1 FROM book_stage_receipts s WHERE s.run_id = r.id "
                "AND s.stage = 'validated' AND s.status = 'succeeded') AS validated, "
                "EXISTS(SELECT 1 FROM book_documents d JOIN book_materializations m "
                "ON m.document_id = d.id AND m.user_id = d.user_id "
                "JOIN active_book_materializations active ON active.materialization_id = m.id "
                "AND active.user_id = m.user_id WHERE d.run_id = r.id AND d.user_id = i.user_id) AS compiled "
                "FROM user_book_imports i JOIN book_assets a ON a.id = i.asset_id "
                "JOIN book_ingestion_runs r ON r.asset_id = a.id AND r.user_id = i.user_id "
                "WHERE i.id = ? AND i.user_id = ? AND r.id = ?",
                (import_id, user_id, run_id),
            ).fetchone()
        if row is None:
            raise KeyError("Unknown Book import.")
        return dict(row)

    def get_book_import_status(
        self,
        *,
        user_id: str,
        import_id: str,
        run_id: str = "",
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            if run_id:
                row = connection.execute(
                    "SELECT i.id AS import_id, i.local_only, a.id AS asset_id, a.sha256, a.byte_size, a.media_type, r.id AS run_id, r.status, r.current_stage, r.error_code FROM user_book_imports i JOIN book_assets a ON a.id = i.asset_id JOIN book_ingestion_runs r ON r.asset_id = a.id WHERE i.id = ? AND i.user_id = ? AND r.id = ? LIMIT 1",
                    (import_id, user_id, run_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT i.id AS import_id, i.local_only, a.id AS asset_id, a.sha256, a.byte_size, a.media_type, r.id AS run_id, r.status, r.current_stage, r.error_code FROM user_book_imports i JOIN book_assets a ON a.id = i.asset_id JOIN book_ingestion_runs r ON r.asset_id = a.id WHERE i.id = ? AND i.user_id = ? ORDER BY r.created_at DESC, r.id DESC LIMIT 1",
                    (import_id, user_id),
                ).fetchone()
            if row is None:
                raise KeyError("Unknown Book import.")
            receipts = connection.execute(
                """
                SELECT id, stage, status, attempt, reason_code, created_at
                FROM book_stage_receipts
                WHERE run_id = ?
                ORDER BY attempt ASC,
                    CASE stage
                        WHEN 'received' THEN 1
                        WHEN 'quarantined' THEN 2
                        WHEN 'validated' THEN 3
                        WHEN 'extracted' THEN 4
                        WHEN 'identified' THEN 5
                        WHEN 'structured' THEN 6
                        WHEN 'skill_compiled' THEN 7
                        WHEN 'indexed' THEN 8
                        WHEN 'ready' THEN 9
                        ELSE 10
                    END ASC,
                    created_at ASC,
                    id ASC
                """,
                (str(row["run_id"]),),
            ).fetchall()
            document = connection.execute(
                "SELECT id, quality_outcome, quality_evaluated FROM book_documents WHERE run_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (str(row["run_id"]),),
            ).fetchone()
        return {
            "import_id": str(row["import_id"]),
            "asset_id": str(row["asset_id"]),
            "run_id": str(row["run_id"]),
            "asset_sha256": str(row["sha256"]),
            "byte_size": int(row["byte_size"]),
            "media_type": str(row["media_type"]),
            "local_only": bool(row["local_only"]),
            "status": str(row["status"]),
            "current_stage": str(row["current_stage"]),
            "error_code": str(row["error_code"] or ""),
            "document_id": str(document["id"]) if document is not None else "",
            "quality_outcome": str(document["quality_outcome"]) if document is not None else "",
            "quality_evaluated": bool(document["quality_evaluated"]) if document is not None else False,
            "receipts": [dict(receipt) for receipt in receipts],
        }

    def find_book_document_status(
        self,
        *,
        user_id: str,
        import_id: str,
        run_id: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT d.id FROM book_documents d JOIN book_ingestion_runs r ON r.id = d.run_id JOIN user_book_imports i ON i.asset_id = r.asset_id WHERE d.id = ? AND d.run_id = ? AND i.id = ? AND i.user_id = ? LIMIT 1",
                (document_id, run_id, import_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return self.get_book_import_status(user_id=user_id, import_id=import_id, run_id=run_id)

    def begin_book_document(
        self,
        *,
        user_id: str,
        import_id: str,
        run_id: str,
        parser_version: str,
        schema_version: str,
    ) -> dict[str, Any]:
        now = _now()
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT a.id AS asset_id, a.sha256 AS asset_sha256, a.byte_size, a.blob_path, r.status, r.attempt_count, d.parser_version AS document_parser_version, d.schema_version AS document_schema_version, EXISTS(SELECT 1 FROM book_stage_receipts s WHERE s.run_id = r.id AND s.stage = 'validated' AND s.status = 'succeeded') AS validated FROM user_book_imports i JOIN book_assets a ON a.id = i.asset_id JOIN book_ingestion_runs r ON r.asset_id = a.id LEFT JOIN book_documents d ON d.run_id = r.id AND d.user_id = i.user_id WHERE i.id = ? AND i.user_id = ? AND r.id = ? LIMIT 1",
                (import_id, user_id, run_id),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown Book import.")
            if not bool(row["validated"]) or not str(row["blob_path"]):
                raise ValueError("BOOK_NOT_VALIDATED")
            if str(row["status"]) in {"rejected", "failed_permanent"}:
                raise ValueError("BOOK_DOCUMENT_NOT_ELIGIBLE")
            if row["document_parser_version"] is not None and (
                str(row["document_parser_version"]) != parser_version
                or str(row["document_schema_version"]) != schema_version
            ):
                raise ValueError("BOOK_DOCUMENT_RUN_VERSION_MISMATCH")
            if str(row["status"]) == "failed_retryable":
                connection.execute(
                    "UPDATE book_ingestion_runs SET attempt_count = attempt_count + 1, status = 'validated', current_stage = 'validated', error_code = '', updated_at = ? WHERE id = ?",
                    (now, run_id),
                )
                attempt = int(row["attempt_count"]) + 1
            else:
                attempt = int(row["attempt_count"])
        return {
            "asset_id": str(row["asset_id"]),
            "asset_sha256": str(row["asset_sha256"]),
            "byte_size": int(row["byte_size"]),
            "blob_path": str(row["blob_path"]),
            "attempt": attempt,
        }

    def publish_book_document(self, publication: BookDocumentPublication) -> dict[str, Any]:
        user_id = publication.user_id
        import_id = publication.import_id
        run_id = publication.run_id
        document_id = publication.document_id
        asset_id = publication.asset_id
        input_digest = publication.input_digest
        document_digest = publication.document_digest
        parser_version = publication.parser_version
        schema_version = publication.schema_version
        now = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT r.attempt_count, a.sha256 AS asset_sha256 FROM book_ingestion_runs r JOIN book_assets a ON a.id = r.asset_id JOIN user_book_imports i ON i.asset_id = r.asset_id WHERE r.id = ? AND r.asset_id = ? AND i.id = ? AND i.user_id = ? AND EXISTS(SELECT 1 FROM book_stage_receipts s WHERE s.run_id = r.id AND s.stage = 'validated' AND s.status = 'succeeded') LIMIT 1",
                (run_id, asset_id, import_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown or unvalidated Book import.")
            if str(row["asset_sha256"]) != input_digest:
                raise ValueError("BOOK_ASSET_DIGEST_MISMATCH")
            existing = connection.execute(
                "SELECT digest, user_id, run_id, asset_id, schema_version, parser_version, input_digest FROM book_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            if existing is not None:
                expected = (
                    user_id,
                    run_id,
                    asset_id,
                    schema_version,
                    parser_version,
                    input_digest,
                    document_digest,
                )
                actual = (
                    str(existing["user_id"]),
                    str(existing["run_id"]),
                    str(existing["asset_id"]),
                    str(existing["schema_version"]),
                    str(existing["parser_version"]),
                    str(existing["input_digest"]),
                    str(existing["digest"]),
                )
                if actual != expected:
                    raise ValueError("BOOK_DOCUMENT_NONDETERMINISTIC")
            connection.execute(
                "INSERT OR IGNORE INTO book_documents (id, user_id, run_id, asset_id, schema_version, parser_version, input_digest, digest, blob_path, quality_outcome, quality_evaluated, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    user_id,
                    run_id,
                    asset_id,
                    schema_version,
                    parser_version,
                    input_digest,
                    document_digest,
                    publication.document_blob_path,
                    publication.quality_outcome,
                    int(publication.quality_evaluated),
                    now,
                ),
            )
            for resource in publication.resources:
                connection.execute(
                    "INSERT OR IGNORE INTO book_document_resources (id, user_id, document_id, manifest_id, resource_path, media_type, source_digest, extracted_digest, artifact_digest, blob_path, byte_size, artifact_byte_size, spine_position, disposition, reason_code, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        resource.id,
                        user_id,
                        document_id,
                        resource.manifest_id,
                        resource.resource_path,
                        resource.media_type,
                        resource.source_digest,
                        resource.extracted_digest,
                        resource.artifact_digest,
                        resource.blob_path,
                        max(0, int(resource.byte_size)),
                        max(0, int(resource.artifact_byte_size)),
                        resource.spine_position,
                        resource.disposition,
                        resource.reason_code,
                        now,
                    ),
                )
            attempt = int(row["attempt_count"])
            extracted_digest = _content_hash(
                "\x1f".join(
                    sorted(resource.artifact_digest for resource in publication.resources if resource.artifact_digest)
                ).encode("utf-8")
            )
            stages = (
                ("extracted", "book-extraction-v1", input_digest, extracted_digest, "EXTRACTED"),
                ("identified", "book-identification-v1", extracted_digest, document_digest, "IDENTIFIED"),
                ("structured", f"{parser_version}:{schema_version}", document_digest, document_digest, "STRUCTURED"),
            )
            for stage, stage_version, stage_input, stage_output, reason_code in stages:
                self._record_book_receipt(
                    connection,
                    run_id=run_id,
                    stage=stage,
                    stage_version=stage_version,
                    input_digest=stage_input,
                    output_digest=stage_output,
                    status="succeeded",
                    attempt=attempt,
                    reason_code=reason_code,
                    metadata=publication.receipt_metadata,
                )
            connection.execute(
                "UPDATE book_ingestion_runs SET status = 'structured', current_stage = 'structured', error_code = '', updated_at = ? WHERE id = ?",
                (now, run_id),
            )
            connection.execute(
                "UPDATE book_assets SET status = 'structured', updated_at = ? WHERE id = ?",
                (now, asset_id),
            )
        return self.get_book_import_status(user_id=user_id, import_id=import_id, run_id=run_id)

    def get_book_document_record(self, *, user_id: str, document_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT d.id, d.digest, d.blob_path, d.quality_outcome FROM book_documents d WHERE d.id = ? AND d.user_id = ? LIMIT 1",
                (document_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError("Unknown BookDocument.")
        return dict(row)

    def begin_book_quality_assessment(
        self,
        *,
        user_id: str,
        import_id: str,
        run_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT d.id, d.digest, d.blob_path, d.schema_version, d.parser_version "
                "FROM book_documents d "
                "JOIN book_ingestion_runs r ON r.id = d.run_id "
                "JOIN user_book_imports i ON i.asset_id = r.asset_id "
                "WHERE d.id = ? AND d.user_id = ? AND d.run_id = ? AND i.id = ? "
                "AND r.status = 'structured' LIMIT 1",
                (document_id, user_id, run_id, import_id),
            ).fetchone()
        if row is None:
            raise KeyError("Unknown structured BookDocument.")
        return dict(row)

    def select_book_quality_assessment_status(
        self,
        *,
        user_id: str,
        import_id: str,
        run_id: str,
        assessment_id: str,
    ) -> dict[str, Any] | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT q.id FROM book_quality_assessments q "
                "JOIN book_documents d ON d.id = q.document_id AND d.user_id = q.user_id "
                "JOIN book_ingestion_runs r ON r.id = d.run_id "
                "JOIN user_book_imports i ON i.asset_id = r.asset_id "
                "WHERE q.id = ? AND q.user_id = ? AND r.id = ? AND i.id = ? LIMIT 1",
                (assessment_id, user_id, run_id, import_id),
            ).fetchone()
        if row is None:
            return None
        return self.activate_book_quality_assessment(
            user_id=user_id,
            import_id=import_id,
            run_id=run_id,
            assessment_id=assessment_id,
        )

    def activate_book_quality_assessment(
        self,
        *,
        user_id: str,
        import_id: str,
        run_id: str,
        assessment_id: str,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            assessment = connection.execute(
                "SELECT q.document_id, q.outcome, q.policy_version, q.policy_snapshot_hash "
                "FROM book_quality_assessments q "
                "JOIN book_documents d ON d.id = q.document_id AND d.user_id = q.user_id "
                "JOIN book_ingestion_runs r ON r.id = d.run_id "
                "JOIN user_book_imports i ON i.asset_id = r.asset_id "
                "WHERE q.id = ? AND q.user_id = ? AND r.id = ? AND i.id = ? LIMIT 1",
                (assessment_id, user_id, run_id, import_id),
            ).fetchone()
            if assessment is None:
                raise KeyError("Unknown Book quality assessment.")
            connection.execute(
                "UPDATE book_documents SET quality_outcome = ?, quality_evaluated = 1, "
                "quality_assessment_id = ?, quality_policy_version = ?, "
                "quality_policy_snapshot_hash = ? WHERE id = ? AND user_id = ?",
                (
                    str(assessment["outcome"]),
                    assessment_id,
                    str(assessment["policy_version"]),
                    str(assessment["policy_snapshot_hash"]),
                    str(assessment["document_id"]),
                    user_id,
                ),
            )
        return self.get_book_import_status(
            user_id=user_id,
            import_id=import_id,
            run_id=run_id,
        )

    def publish_book_quality_assessment(
        self,
        publication: BookQualityAssessmentPublication,
    ) -> dict[str, Any]:
        now = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            document = connection.execute(
                "SELECT d.digest FROM book_documents d "
                "JOIN book_ingestion_runs r ON r.id = d.run_id "
                "JOIN user_book_imports i ON i.asset_id = r.asset_id "
                "WHERE d.id = ? AND d.user_id = ? AND r.id = ? AND i.id = ? "
                "AND r.status = 'structured' LIMIT 1",
                (
                    publication.document_id,
                    publication.user_id,
                    publication.run_id,
                    publication.import_id,
                ),
            ).fetchone()
            if document is None:
                raise KeyError("Unknown structured BookDocument.")
            if str(document["digest"]) != publication.document_digest:
                raise ValueError("BOOK_DOCUMENT_DIGEST_MISMATCH")
            existing = connection.execute(
                "SELECT user_id, document_id, document_digest, policy_version, policy_snapshot_hash, "
                "outcome, report_digest, blob_path FROM book_quality_assessments WHERE id = ?",
                (publication.assessment_id,),
            ).fetchone()
            if existing is not None:
                expected = (
                    publication.user_id,
                    publication.document_id,
                    publication.document_digest,
                    publication.policy_version,
                    publication.policy_snapshot_hash,
                    publication.outcome,
                    publication.report_digest,
                    publication.report_blob_path,
                )
                actual = tuple(str(existing[key]) for key in existing.keys())
                if actual != expected:
                    raise ValueError("BOOK_QUALITY_ASSESSMENT_NONDETERMINISTIC")
            connection.execute(
                "INSERT OR IGNORE INTO book_quality_assessments "
                "(id, user_id, document_id, document_digest, policy_version, policy_snapshot_hash, "
                "outcome, report_digest, blob_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    publication.assessment_id,
                    publication.user_id,
                    publication.document_id,
                    publication.document_digest,
                    publication.policy_version,
                    publication.policy_snapshot_hash,
                    publication.outcome,
                    publication.report_digest,
                    publication.report_blob_path,
                    now,
                ),
            )
            stored = connection.execute(
                "SELECT id, user_id, outcome, report_digest, blob_path "
                "FROM book_quality_assessments WHERE document_id = ? AND document_digest = ? "
                "AND policy_version = ? AND policy_snapshot_hash = ? LIMIT 1",
                (
                    publication.document_id,
                    publication.document_digest,
                    publication.policy_version,
                    publication.policy_snapshot_hash,
                ),
            ).fetchone()
            expected_stored = (
                publication.assessment_id,
                publication.user_id,
                publication.outcome,
                publication.report_digest,
                publication.report_blob_path,
            )
            if stored is None or tuple(str(stored[key]) for key in stored.keys()) != expected_stored:
                raise ValueError("BOOK_QUALITY_ASSESSMENT_NONDETERMINISTIC")
            connection.execute(
                "UPDATE book_documents SET quality_outcome = ?, quality_evaluated = 1, "
                "quality_assessment_id = ?, quality_policy_version = ?, "
                "quality_policy_snapshot_hash = ? "
                "WHERE id = ? AND user_id = ?",
                (
                    publication.outcome,
                    publication.assessment_id,
                    publication.policy_version,
                    publication.policy_snapshot_hash,
                    publication.document_id,
                    publication.user_id,
                ),
            )
        return self.get_book_import_status(
            user_id=publication.user_id,
            import_id=publication.import_id,
            run_id=publication.run_id,
        )

    def require_passed_book_document(
        self,
        *,
        user_id: str,
        document_id: str,
        policy_version: str,
        policy_snapshot_hash: str,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            document = connection.execute(
                "SELECT id, digest, blob_path, quality_outcome FROM book_documents "
                "WHERE id = ? AND user_id = ? LIMIT 1",
                (document_id, user_id),
            ).fetchone()
            if document is None:
                raise KeyError("Unknown BookDocument.")
            assessment = connection.execute(
                "SELECT outcome FROM book_quality_assessments "
                "WHERE document_id = ? AND user_id = ? AND document_digest = ? "
                "AND policy_version = ? AND policy_snapshot_hash = ? LIMIT 1",
                (
                    document_id,
                    user_id,
                    str(document["digest"]),
                    policy_version,
                    policy_snapshot_hash,
                ),
            ).fetchone()
        if assessment is None or str(assessment["outcome"]) != "PASS":
            raise ValueError("BOOK_QUALITY_NOT_PASSED")
        return dict(document)

    def get_book_quality_assessment_record(
        self,
        *,
        user_id: str,
        document_id: str,
        policy_version: str,
        policy_snapshot_hash: str,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT q.id, q.document_id, q.document_digest, q.policy_version, "
                "q.policy_snapshot_hash, q.outcome, q.report_digest, q.blob_path "
                "FROM book_quality_assessments q "
                "JOIN book_documents d ON d.id = q.document_id AND d.user_id = q.user_id "
                "WHERE q.document_id = ? AND q.user_id = ? AND q.document_digest = d.digest "
                "AND q.policy_version = ? AND q.policy_snapshot_hash = ? LIMIT 1",
                (document_id, user_id, policy_version, policy_snapshot_hash),
            ).fetchone()
        if row is None:
            raise KeyError("Unknown Book quality assessment.")
        return dict(row)

    def begin_book_materialization(
        self,
        *,
        user_id: str,
        import_id: str,
        run_id: str,
        document_id: str,
        policy_version: str,
        policy_snapshot_hash: str,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT d.id AS document_id, d.digest AS document_digest, "
                "q.id AS quality_assessment_id, q.policy_version, q.policy_snapshot_hash, "
                "q.report_digest AS quality_report_digest "
                "FROM book_documents d "
                "JOIN book_ingestion_runs r ON r.id = d.run_id AND r.user_id = d.user_id "
                "JOIN user_book_imports i ON i.asset_id = r.asset_id AND i.user_id = d.user_id "
                "JOIN book_quality_assessments q ON q.id = d.quality_assessment_id "
                "AND q.document_id = d.id AND q.user_id = d.user_id "
                "WHERE d.id = ? AND d.user_id = ? AND r.id = ? AND i.id = ? "
                "AND q.document_digest = d.digest AND q.outcome = 'PASS' "
                "AND q.policy_version = ? AND q.policy_snapshot_hash = ? LIMIT 1",
                (
                    document_id,
                    user_id,
                    run_id,
                    import_id,
                    policy_version,
                    policy_snapshot_hash,
                ),
            ).fetchone()
        if row is None:
            raise ValueError("BOOK_MATERIALIZATION_NOT_ELIGIBLE")
        return dict(row)

    def find_book_materialization_status(
        self,
        *,
        user_id: str,
        materialization_id: str,
    ) -> dict[str, Any] | None:
        with closing(self._connect()) as connection, connection:
            row = self._book_materialization_status_row(
                connection,
                user_id=user_id,
                materialization_id=materialization_id,
            )
        return self._book_materialization_status(row) if row is not None else None

    def begin_book_materialization_candidate(
        self,
        *,
        user_id: str,
        materialization_id: str,
    ) -> None:
        now = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO book_materialization_candidates "
                "(materialization_id, user_id, artifact_paths_json, created_at, updated_at) "
                "VALUES (?, ?, '[]', ?, ?)",
                (materialization_id, user_id, now, now),
            )

    def record_book_materialization_candidate_artifact(
        self,
        *,
        user_id: str,
        materialization_id: str,
        blob_path: str,
    ) -> None:
        now = _now()
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT artifact_paths_json FROM book_materialization_candidates "
                "WHERE materialization_id = ? AND user_id = ? LIMIT 1",
                (materialization_id, user_id),
            ).fetchone()
            if row is None:
                # A concurrent publisher may have completed and removed the candidate.
                return
            try:
                paths = json.loads(str(row["artifact_paths_json"] or "[]"))
            except json.JSONDecodeError:
                paths = []
            if not isinstance(paths, list):
                paths = []
            if blob_path not in paths:
                paths.append(blob_path)
            connection.execute(
                "UPDATE book_materialization_candidates SET artifact_paths_json = ?, "
                "updated_at = ? WHERE materialization_id = ? AND user_id = ?",
                (_json(paths), now, materialization_id, user_id),
            )

    def abandon_book_materialization_candidate(
        self,
        *,
        user_id: str,
        materialization_id: str,
        artifact_paths: Iterable[str] = (),
    ) -> int:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT artifact_paths_json FROM book_materialization_candidates "
                "WHERE materialization_id = ? AND user_id = ? LIMIT 1",
                (materialization_id, user_id),
            ).fetchone()
            if row is not None:
                try:
                    recorded = json.loads(str(row["artifact_paths_json"] or "[]"))
                except json.JSONDecodeError:
                    recorded = []
                if not isinstance(recorded, list):
                    recorded = []
                paths = [str(path) for path in recorded if isinstance(path, str)]
                paths.extend(str(path) for path in artifact_paths)
                connection.execute(
                    "DELETE FROM book_materialization_candidates "
                    "WHERE materialization_id = ? AND user_id = ?",
                    (materialization_id, user_id),
                )
            else:
                paths = [str(path) for path in artifact_paths]
            referenced = self._book_artifact_references(connection)
        return self._remove_unreferenced_book_artifacts(paths, referenced=referenced)

    def find_stale_book_materialization_candidates(
        self,
        *,
        older_than: timedelta = timedelta(hours=24),
    ) -> list[tuple[str, str]]:
        cutoff = (datetime.now(UTC) - older_than).isoformat()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT materialization_id, user_id "
                "FROM book_materialization_candidates WHERE updated_at < ?",
                (cutoff,),
            ).fetchall()
        return [
            (str(row["user_id"]), str(row["materialization_id"]))
            for row in rows
        ]

    @staticmethod
    def _book_artifact_references(connection: sqlite3.Connection) -> set[str]:
        references = {
            str(row[0])
            for row in connection.execute(
                "SELECT blob_path FROM book_assets WHERE blob_path <> '' "
                "UNION ALL SELECT blob_path FROM book_documents WHERE blob_path <> '' "
                "UNION ALL SELECT blob_path FROM book_document_resources WHERE blob_path <> '' "
                "UNION ALL SELECT blob_path FROM book_quality_assessments WHERE blob_path <> ''"
            ).fetchall()
        }
        for row in connection.execute(
            "SELECT blob_path, artifact_paths_json FROM book_materializations"
        ).fetchall():
            if str(row["blob_path"] or ""):
                references.add(str(row["blob_path"]))
            try:
                paths = json.loads(str(row["artifact_paths_json"] or "[]"))
            except json.JSONDecodeError:
                paths = []
            if isinstance(paths, list):
                references.update(str(path) for path in paths if isinstance(path, str))
        for row in connection.execute(
            "SELECT artifact_paths_json FROM book_materialization_candidates"
        ).fetchall():
            try:
                paths = json.loads(str(row["artifact_paths_json"] or "[]"))
            except json.JSONDecodeError:
                paths = []
            if isinstance(paths, list):
                references.update(str(path) for path in paths if isinstance(path, str))
        return references

    def _remove_unreferenced_book_artifacts(
        self,
        paths: Iterable[str],
        *,
        referenced: set[str],
    ) -> int:
        removed = 0
        for relative_path in set(paths):
            if not relative_path or relative_path in referenced:
                continue
            try:
                target = self.blobs.resolve(relative_path)
                if target.exists():
                    target.unlink()
                    removed += 1
            except (OSError, ValueError):
                continue
        return removed

    def publish_book_materialization(
        self,
        publication: BookMaterializationPublication,
    ) -> dict[str, Any]:
        now = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            source = connection.execute(
                "SELECT r.attempt_count, d.digest, q.id AS quality_assessment_id, "
                "q.policy_snapshot_hash, q.outcome "
                "FROM book_documents d "
                "JOIN book_ingestion_runs r ON r.id = d.run_id AND r.user_id = d.user_id "
                "JOIN user_book_imports i ON i.asset_id = r.asset_id AND i.user_id = d.user_id "
                "JOIN book_quality_assessments q ON q.id = d.quality_assessment_id "
                "AND q.document_id = d.id AND q.user_id = d.user_id "
                "WHERE d.id = ? AND d.user_id = ? AND r.id = ? AND i.id = ? LIMIT 1",
                (
                    publication.document_id,
                    publication.user_id,
                    publication.run_id,
                    publication.import_id,
                ),
            ).fetchone()
            if source is None:
                raise ValueError("BOOK_MATERIALIZATION_NOT_ELIGIBLE")
            if (
                str(source["digest"]) != publication.document_digest
                or str(source["quality_assessment_id"]) != publication.quality_assessment_id
                or str(source["policy_snapshot_hash"]) != publication.policy_snapshot_hash
                or str(source["outcome"]) != "PASS"
            ):
                raise ValueError("BOOK_MATERIALIZATION_NOT_ELIGIBLE")
            existing = connection.execute(
                "SELECT user_id, edition_id, document_id, document_digest, quality_assessment_id, "
                "schema_version, compiler_version, model_version, prompt_version, embedding_model, "
                "embedding_model_revision, "
                "policy_snapshot_hash, bundle_digest, blob_path, skill_id, skill_version, "
                "index_collection, index_count, artifact_paths_json, "
                "chunk_count, citation_count, embedding_count "
                "FROM book_materializations WHERE id = ?",
                (publication.materialization_id,),
            ).fetchone()
            expected = (
                publication.user_id,
                publication.edition_id,
                publication.document_id,
                publication.document_digest,
                publication.quality_assessment_id,
                publication.schema_version,
                publication.compiler_version,
                publication.model_version,
                publication.prompt_version,
                publication.embedding_model,
                publication.embedding_model_revision,
                publication.policy_snapshot_hash,
                publication.bundle_digest,
                publication.bundle_blob_path,
                publication.skill_id,
                publication.skill_version,
                publication.index_collection,
                publication.index_count,
                _json(list(publication.artifact_paths)),
                publication.chunk_count,
                publication.citation_count,
                publication.embedding_count,
            )
            if existing is not None and tuple(existing) != expected:
                raise ValueError("BOOK_MATERIALIZATION_NONDETERMINISTIC")
            connection.execute(
                "INSERT OR IGNORE INTO book_materializations "
                "(id, user_id, edition_id, document_id, document_digest, quality_assessment_id, "
                "schema_version, compiler_version, model_version, prompt_version, embedding_model, "
                "embedding_model_revision, "
                "policy_snapshot_hash, bundle_digest, blob_path, skill_id, skill_version, "
                "index_collection, index_count, artifact_paths_json, "
                "chunk_count, citation_count, embedding_count, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (publication.materialization_id, *expected, now),
            )
            attempt = int(source["attempt_count"])
            receipt_metadata = {
                "schema_version": publication.schema_version,
                "compiler_version": publication.compiler_version,
                "model_version": publication.model_version,
                "prompt_version": publication.prompt_version,
                "embedding_model": publication.embedding_model,
                "embedding_model_revision": publication.embedding_model_revision,
                "index_collection": publication.index_collection,
                "index_count": publication.index_count,
                "chunk_count": publication.chunk_count,
                "citation_count": publication.citation_count,
                "embedding_count": publication.embedding_count,
            }
            stages = (
                (
                    "skill_compiled",
                    f"{publication.compiler_version}:{publication.model_version}:{publication.prompt_version}",
                    publication.document_digest,
                    publication.bundle_digest,
                    "BOOK_SKILL_COMPILED",
                ),
                (
                    "indexed",
                    publication.embedding_model,
                    publication.bundle_digest,
                    publication.bundle_digest,
                    "BOOK_INDEXED",
                ),
                (
                    "ready",
                    publication.schema_version,
                    publication.bundle_digest,
                    publication.materialization_id,
                    "BOOK_READY",
                ),
            )
            for stage, stage_version, input_digest, output_digest, reason_code in stages:
                self._record_book_receipt(
                    connection,
                    run_id=publication.run_id,
                    stage=stage,
                    stage_version=stage_version,
                    input_digest=input_digest,
                    output_digest=output_digest,
                    status="succeeded",
                    attempt=attempt,
                    reason_code=reason_code,
                    metadata=receipt_metadata,
                )
            connection.execute(
                "INSERT INTO active_book_materializations "
                "(user_id, edition_id, materialization_id, activated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, edition_id) DO UPDATE SET "
                "materialization_id = excluded.materialization_id, activated_at = excluded.activated_at",
                (
                    publication.user_id,
                    publication.edition_id,
                    publication.materialization_id,
                    now,
                ),
            )
            connection.execute(
                "UPDATE book_ingestion_runs SET status = 'ready', current_stage = 'ready', "
                "error_code = '', updated_at = ? WHERE id = ? AND user_id = ?",
                (now, publication.run_id, publication.user_id),
            )
            connection.execute(
                "UPDATE book_assets SET status = 'ready', updated_at = ? "
                "WHERE id = (SELECT asset_id FROM book_ingestion_runs WHERE id = ? AND user_id = ?)",
                (now, publication.run_id, publication.user_id),
            )
            connection.execute(
                "DELETE FROM book_materialization_candidates WHERE materialization_id = ? "
                "AND user_id = ?",
                (publication.materialization_id, publication.user_id),
            )
            row = self._book_materialization_status_row(
                connection,
                user_id=publication.user_id,
                materialization_id=publication.materialization_id,
            )
            if row is None:
                raise ValueError("BOOK_MATERIALIZATION_PUBLICATION_FAILED")
        return self._book_materialization_status(row)

    def get_book_materialization_record(
        self,
        *,
        user_id: str,
        materialization_id: str,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT id, user_id, edition_id, document_id, document_digest, "
                "quality_assessment_id, schema_version, compiler_version, model_version, "
                "prompt_version, embedding_model, embedding_model_revision, "
                "policy_snapshot_hash, bundle_digest, blob_path, skill_id, skill_version, "
                "index_collection, index_count, artifact_paths_json, chunk_count, "
                "citation_count, embedding_count FROM book_materializations "
                "WHERE id = ? AND user_id = ? LIMIT 1",
                (materialization_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError("Unknown Book materialization.")
        return dict(row)

    def get_active_book_materialization_record(
        self,
        *,
        user_id: str,
        edition_id: str,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT m.id, m.user_id, m.edition_id, m.document_id, m.document_digest, "
                "m.quality_assessment_id, m.schema_version, m.compiler_version, "
                "m.model_version, m.prompt_version, m.embedding_model, "
                "m.embedding_model_revision, m.policy_snapshot_hash, m.bundle_digest, "
                "m.blob_path, m.skill_id, m.skill_version, m.index_collection, "
                "m.index_count, m.artifact_paths_json, m.chunk_count, m.citation_count, "
                "m.embedding_count FROM book_materializations m "
                "JOIN active_book_materializations a ON a.materialization_id = m.id "
                "AND a.user_id = m.user_id AND a.edition_id = m.edition_id "
                "WHERE a.user_id = ? AND a.edition_id = ? LIMIT 1",
                (user_id, edition_id),
            ).fetchone()
        if row is None:
            raise KeyError("Unknown active Book materialization.")
        return dict(row)

    def list_active_book_materialization_records(
        self,
        *,
        user_id: str,
    ) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT m.id, m.user_id, m.edition_id, m.document_id, m.document_digest, "
                "m.quality_assessment_id, m.schema_version, m.compiler_version, "
                "m.model_version, m.prompt_version, m.embedding_model, "
                "m.embedding_model_revision, m.policy_snapshot_hash, m.bundle_digest, "
                "m.blob_path, m.skill_id, m.skill_version, m.index_collection, "
                "m.index_count, m.artifact_paths_json, m.chunk_count, m.citation_count, "
                "m.embedding_count, i.local_only FROM book_materializations m "
                "JOIN active_book_materializations a ON a.materialization_id = m.id "
                "AND a.user_id = m.user_id AND a.edition_id = m.edition_id "
                "JOIN book_documents d ON d.id = m.document_id AND d.user_id = m.user_id "
                "JOIN book_ingestion_runs r ON r.id = d.run_id AND r.user_id = m.user_id "
                "JOIN user_book_imports i ON i.asset_id = r.asset_id AND i.user_id = m.user_id "
                "WHERE a.user_id = ? ORDER BY a.activated_at DESC, m.id ASC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_book_retrieval_receipt(
        self,
        *,
        user_id: str,
        query: str,
        destination: str,
        active_count: int,
        candidate_count: int,
        evidence_count: int,
        token_budget: int,
        tokens_used: int,
    ) -> str:
        tenant_scope = self.book_tenant_scope(user_id)
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        created_at = _now()
        receipt_id = _stable_id(
            "brr",
            tenant_scope,
            query_hash,
            destination,
            created_at,
        )
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO book_retrieval_receipts "
                "(id, tenant_scope, query_hash, destination, active_count, candidate_count, "
                "evidence_count, token_budget, tokens_used, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    receipt_id,
                    tenant_scope,
                    query_hash,
                    destination,
                    max(0, int(active_count)),
                    max(0, int(candidate_count)),
                    max(0, int(evidence_count)),
                    max(0, int(token_budget)),
                    max(0, int(tokens_used)),
                    created_at,
                ),
            )
        return receipt_id

    def get_active_book_materialization_status(
        self,
        *,
        user_id: str,
        edition_id: str,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            active = connection.execute(
                "SELECT materialization_id FROM active_book_materializations "
                "WHERE user_id = ? AND edition_id = ? LIMIT 1",
                (user_id, edition_id),
            ).fetchone()
            row = (
                self._book_materialization_status_row(
                    connection,
                    user_id=user_id,
                    materialization_id=str(active["materialization_id"]),
                )
                if active is not None
                else None
            )
        if row is None:
            raise KeyError("Unknown active Book materialization.")
        return self._book_materialization_status(row)

    @staticmethod
    def _book_materialization_status_row(
        connection: sqlite3.Connection,
        *,
        user_id: str,
        materialization_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT m.id AS materialization_id, m.edition_id, m.document_id, "
            "m.document_digest, m.quality_assessment_id, m.skill_id, m.skill_version, "
            "m.compiler_version, m.model_version, m.prompt_version, m.embedding_model, "
            "m.embedding_model_revision, m.policy_snapshot_hash, m.index_collection, "
            "m.index_count, m.chunk_count, m.citation_count, m.embedding_count, "
            "CASE WHEN a.materialization_id = m.id THEN 1 ELSE 0 END AS active "
            "FROM book_materializations m "
            "LEFT JOIN active_book_materializations a ON a.user_id = m.user_id "
            "AND a.edition_id = m.edition_id "
            "WHERE m.id = ? AND m.user_id = ? LIMIT 1",
            (materialization_id, user_id),
        ).fetchone()

    @staticmethod
    def _book_materialization_status(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "materialization_id": str(row["materialization_id"]),
            "edition_id": str(row["edition_id"]),
            "document_id": str(row["document_id"]),
            "document_digest": str(row["document_digest"]),
            "quality_assessment_id": str(row["quality_assessment_id"]),
            "state": "ready",
            "active": bool(row["active"]),
            "skill_id": str(row["skill_id"]),
            "skill_version": str(row["skill_version"]),
            "compiler_version": str(row["compiler_version"]),
            "model_version": str(row["model_version"]),
            "prompt_version": str(row["prompt_version"]),
            "embedding_model": str(row["embedding_model"]),
            "embedding_model_revision": str(row["embedding_model_revision"]),
            "policy_snapshot_hash": str(row["policy_snapshot_hash"]),
            "index_collection": str(row["index_collection"]),
            "index_count": int(row["index_count"]),
            "chunk_count": int(row["chunk_count"]),
            "citation_count": int(row["citation_count"]),
            "embedding_count": int(row["embedding_count"]),
        }

    def record_entity_identities(
        self,
        items: Iterable[EntityIdentityInput],
    ) -> dict[str, int]:
        entities_created = 0
        entities_existing = 0
        aliases_created = 0
        aliases_existing = 0
        now = _now()
        with closing(self._connect()) as connection, connection:
            for item in items:
                identity_key = item.external_id.casefold()
                entity_id = _stable_id("ent", item.entity_type.casefold(), identity_key)
                existing = connection.execute(
                    "SELECT id, canonical_name, metadata_json FROM entities WHERE id = ?",
                    (entity_id,),
                ).fetchone()
                incoming_observed_at = _iso(item.observed_at)
                existing_metadata = (
                    json.loads(str(existing["metadata_json"] or "{}"))
                    if existing is not None
                    else {}
                )
                existing_observed_at = _parse_datetime(
                    existing_metadata.get("observed_at")
                )
                incoming_datetime = _parse_datetime(incoming_observed_at)
                use_incoming = (
                    existing is None
                    or existing_observed_at is None
                    or (
                        incoming_datetime is not None
                        and incoming_datetime >= existing_observed_at
                    )
                )
                canonical_name = (
                    item.canonical_name
                    if use_incoming or existing is None
                    else str(existing["canonical_name"])
                )
                metadata = {
                    **existing_metadata,
                    **item.metadata,
                    "external_id": item.external_id,
                    "identity_key": identity_key,
                    "observed_at": (
                        incoming_observed_at
                        if use_incoming or existing is None
                        else str(existing_metadata.get("observed_at") or "")
                    ),
                }
                connection.execute(
                    """
                    INSERT INTO entities (
                        id, entity_type, canonical_name, normalized_name,
                        sensitivity, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        canonical_name = excluded.canonical_name,
                        sensitivity = excluded.sensitivity,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    WHERE canonical_name IS NOT excluded.canonical_name
                       OR sensitivity IS NOT excluded.sensitivity
                       OR metadata_json IS NOT excluded.metadata_json
                    """,
                    (
                        entity_id,
                        item.entity_type,
                        canonical_name,
                        identity_key,
                        item.sensitivity.value,
                        _json(metadata),
                        now,
                        now,
                    ),
                )
                if existing is None:
                    entities_created += 1
                else:
                    entities_existing += 1

                for alias in item.aliases:
                    normalized_alias = " ".join(alias.casefold().split())
                    if not normalized_alias:
                        continue
                    alias_id = _stable_id("alias", entity_id, normalized_alias)
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO entity_aliases (
                            id, entity_id, alias, normalized_alias, source_id, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            alias_id,
                            entity_id,
                            alias,
                            normalized_alias,
                            item.source_id,
                            now,
                        ),
                    )
                    if int(cursor.rowcount) > 0:
                        aliases_created += 1
                    else:
                        aliases_existing += 1
        return {
            "entities_created": entities_created,
            "entities_existing": entities_existing,
            "aliases_created": aliases_created,
            "aliases_existing": aliases_existing,
        }

    def get_entity_identity(
        self,
        *,
        entity_type: str,
        external_id: str,
    ) -> dict[str, Any] | None:
        identities = self.get_entity_identities(
            entity_type=entity_type,
            external_ids=(external_id,),
        )
        return identities.get(external_id.strip().casefold())

    def get_entity_identities(
        self,
        *,
        entity_type: str,
        external_ids: Iterable[str],
    ) -> dict[str, dict[str, Any]]:
        identity_keys = sorted(
            {
                external_id.strip().casefold()
                for external_id in external_ids
                if external_id.strip()
            }
        )
        if not identity_keys:
            return {}
        placeholders = ", ".join("?" for _ in identity_keys)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                SELECT * FROM entities
                WHERE entity_type = ? AND normalized_name IN ({placeholders})
                ORDER BY normalized_name ASC
                """,
                (entity_type, *identity_keys),
            ).fetchall()
            entity_ids = [str(row["id"]) for row in rows]
            aliases_by_entity: dict[str, list[str]] = {
                entity_id: [] for entity_id in entity_ids
            }
            if entity_ids:
                entity_placeholders = ", ".join("?" for _ in entity_ids)
                aliases = connection.execute(
                    f"""
                    SELECT entity_id, alias FROM entity_aliases
                    WHERE entity_id IN ({entity_placeholders})
                    ORDER BY entity_id ASC, normalized_alias ASC
                    """,
                    entity_ids,
                ).fetchall()
                for alias in aliases:
                    aliases_by_entity[str(alias["entity_id"])].append(
                        str(alias["alias"])
                    )
        identities: dict[str, dict[str, Any]] = {}
        for row in rows:
            entity_id = str(row["id"])
            metadata = json.loads(str(row["metadata_json"] or "{}"))
            identity = {
                "entity_id": entity_id,
                "entity_type": str(row["entity_type"]),
                "external_id": str(
                    metadata.get("external_id") or row["normalized_name"]
                ),
                "canonical_name": str(row["canonical_name"]),
                "aliases": aliases_by_entity[entity_id],
                "sensitivity": str(row["sensitivity"]),
                "metadata": metadata,
                "updated_at": str(row["updated_at"]),
            }
            identities[str(identity["external_id"]).casefold()] = identity
        return identities

    def entity_identity_profile(
        self,
        *,
        entity_type: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 500))
        with closing(self._connect()) as connection, connection:
            entity_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM entities WHERE entity_type = ?",
                    (entity_type,),
                ).fetchone()[0]
            )
            alias_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM entity_aliases aliases
                    JOIN entities entities ON entities.id = aliases.entity_id
                    WHERE entities.entity_type = ?
                    """,
                    (entity_type,),
                ).fetchone()[0]
            )
            collision_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT aliases.normalized_alias
                        FROM entity_aliases aliases
                        JOIN entities entities ON entities.id = aliases.entity_id
                        WHERE entities.entity_type = ?
                        GROUP BY aliases.normalized_alias
                        HAVING COUNT(DISTINCT aliases.entity_id) > 1
                    )
                    """,
                    (entity_type,),
                ).fetchone()[0]
            )
            collisions = connection.execute(
                """
                SELECT aliases.normalized_alias, MIN(aliases.alias) AS alias
                FROM entity_aliases aliases
                JOIN entities entities ON entities.id = aliases.entity_id
                WHERE entities.entity_type = ?
                GROUP BY aliases.normalized_alias
                HAVING COUNT(DISTINCT aliases.entity_id) > 1
                ORDER BY aliases.normalized_alias ASC
                LIMIT ?
                """,
                (entity_type, bounded_limit),
            ).fetchall()
            collision_aliases = [str(row["normalized_alias"]) for row in collisions]
            entities_by_alias: dict[str, list[sqlite3.Row]] = {
                alias: [] for alias in collision_aliases
            }
            if collision_aliases:
                alias_placeholders = ", ".join("?" for _ in collision_aliases)
                collision_entities = connection.execute(
                    f"""
                    SELECT aliases.normalized_alias, entities.id, entities.metadata_json
                    FROM entity_aliases aliases
                    JOIN entities entities ON entities.id = aliases.entity_id
                    WHERE entities.entity_type = ?
                      AND aliases.normalized_alias IN ({alias_placeholders})
                    ORDER BY aliases.normalized_alias ASC, entities.id ASC
                    """,
                    (entity_type, *collision_aliases),
                ).fetchall()
                for entity in collision_entities:
                    entities_by_alias[str(entity["normalized_alias"])].append(entity)
            items = []
            for collision in collisions:
                entities = entities_by_alias[str(collision["normalized_alias"])]
                items.append(
                    {
                        "normalized_alias": str(collision["normalized_alias"]),
                        "alias": str(collision["alias"]),
                        "entities": [
                            {
                                "entity_id": str(entity["id"]),
                                "external_id": str(
                                    json.loads(str(entity["metadata_json"] or "{}"))
                                    .get("external_id")
                                    or ""
                                ),
                            }
                            for entity in entities
                        ],
                    }
                )
        return {
            "counts": {
                "entities": entity_count,
                "aliases": alias_count,
                "collision_candidates": collision_count,
            },
            "collisions": items,
        }

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

        with closing(self._connect()) as connection, connection:
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
        with closing(self._connect()) as connection, connection:
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

    def record_observations(self, items: Iterable[ObservationInput]) -> dict[str, int]:
        created = 0
        existing_count = 0
        with closing(self._connect()) as connection, connection:
            for item in items:
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
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO observations (
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
                        _now(),
                    ),
                )
                if int(cursor.rowcount) > 0:
                    created += 1
                else:
                    existing_count += 1
        return {"created": created, "existing": existing_count}

    def count_observations(self, *, origin: str = "", action: str = "") -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if origin:
            clauses.append("origin = ?")
            params.append(origin)
        if action:
            clauses.append("action = ?")
            params.append(action)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with closing(self._connect()) as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM observations {where}", params).fetchone()[0])

    def propose_user_learning_candidate(
        self,
        item: BookUserLearningCandidateInput,
        *,
        observation_id: str,
    ) -> dict[str, Any]:
        dedupe_key = _stable_id(
            "ulk",
            item.user_id,
            item.proposition_type,
            _normalized_proposition(item.proposition),
            item.scope,
        )
        candidate_id = _stable_id("ulc", item.user_id, dedupe_key)
        now = _now()
        references = [
            *item.evidence,
            BookUserLearningEvidenceReference(
                kind="observation",
                reference_id=observation_id,
                stance="supports",
            ),
        ]
        unique_references = {
            (reference.kind, reference.reference_id, reference.stance): reference
            for reference in references
        }
        with closing(self._connect()) as connection, connection:
            existing = connection.execute(
                "SELECT id, lifecycle FROM user_learning_candidates WHERE user_id = ? AND dedupe_key = ?",
                (item.user_id, dedupe_key),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO user_learning_candidates (
                        id, user_id, dedupe_key, proposition_type, proposition, basis,
                        actor, confidence, sensitivity, scope, permitted_uses_json,
                        lifecycle, valid_from, valid_to, expires_at, derivation,
                        source_agent, model_version, prompt_version, policy_version,
                        schema_version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        item.user_id,
                        dedupe_key,
                        item.proposition_type,
                        item.proposition,
                        item.basis,
                        item.actor.value,
                        float(item.confidence),
                        item.sensitivity.value,
                        item.scope,
                        _json(item.permitted_uses),
                        _iso(item.valid_from),
                        _iso(item.valid_to),
                        _iso(item.expires_at),
                        item.derivation,
                        item.source_agent,
                        item.model_version,
                        item.prompt_version,
                        item.policy_version,
                        item.schema_version,
                        now,
                        now,
                    ),
                )
                lifecycle = "proposed"
            else:
                candidate_id = str(existing["id"])
                lifecycle = str(existing["lifecycle"])

            evidence_added = 0
            for reference in unique_references.values():
                evidence_id = _stable_id(
                    "ule",
                    candidate_id,
                    reference.kind,
                    reference.reference_id,
                    reference.stance,
                )
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO user_learning_candidate_evidence (
                        id, candidate_id, kind, reference_id, stance, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence_id,
                        candidate_id,
                        reference.kind,
                        reference.reference_id,
                        reference.stance,
                        now,
                    ),
                )
                evidence_added += int(cursor.rowcount) > 0
            evidence_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM user_learning_candidate_evidence WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()[0]
            )
        return {
            "candidate_id": candidate_id,
            "created": existing is None,
            "lifecycle": lifecycle,
            "evidence_added": evidence_added,
            "evidence_count": evidence_count,
        }

    def get_user_learning_candidate(
        self,
        *,
        user_id: str,
        candidate_id: str,
    ) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM user_learning_candidates WHERE id = ? AND user_id = ?",
                (candidate_id, user_id),
            ).fetchone()
            if row is None:
                return None
            evidence = connection.execute(
                """
                SELECT kind, reference_id, stance
                FROM user_learning_candidate_evidence
                WHERE candidate_id = ?
                ORDER BY stance, kind, reference_id
                """,
                (candidate_id,),
            ).fetchall()
        result = dict(row)
        result["permitted_uses"] = json.loads(str(result.pop("permitted_uses_json") or "[]"))
        result["evidence"] = [dict(item) for item in evidence]
        return result

    def propose_book_wisdom(self, item: BookWisdomRecordInput) -> dict[str, Any]:
        item = BookWisdomRecordInput.model_validate(item.model_dump(mode="python"))
        candidate_ids = list(
            dict.fromkeys(
                reference.reference_id
                for reference in item.evidence
                if reference.kind == "user_learning_candidate"
            )
        )
        placeholders = ", ".join("?" for _ in candidate_ids)
        with closing(self._connect()) as connection:
            candidates = connection.execute(
                f"""
                SELECT id, user_id, lifecycle, sensitivity, permitted_uses_json
                FROM user_learning_candidates
                WHERE id IN ({placeholders})
                """,
                candidate_ids,
            ).fetchall()
        candidate_by_id = {str(row["id"]): row for row in candidates}
        if set(candidate_ids) != set(candidate_by_id) or any(
            str(row["user_id"]) != item.user_id for row in candidates
        ):
            raise ValueError("Book Wisdom requires a same-user learning candidate")
        for candidate in candidates:
            if "wisdom" not in json.loads(str(candidate["permitted_uses_json"] or "[]")):
                raise ValueError("User-learning candidate is not permitted for Wisdom")
            if str(candidate["lifecycle"]) in {"rejected", "superseded", "expired"}:
                raise ValueError("Inactive user-learning candidate cannot support Wisdom")
            if (
                str(candidate["sensitivity"]) == "sensitive"
                and item.sensitivity.value != "sensitive"
            ):
                raise ValueError("Book Wisdom cannot reduce user-evidence sensitivity")

        record_key = _stable_id(
            "wkey",
            item.user_id,
            item.wisdom_type,
            _normalized_proposition(item.content),
        )
        wisdom_id = _stable_id("wis", item.user_id, record_key)
        now = _now()
        unique_evidence = {
            (reference.kind, reference.reference_id, reference.stance): reference
            for reference in item.evidence
        }
        with closing(self._connect()) as connection, connection:
            existing = connection.execute(
                """
                SELECT id, status
                FROM derived_insights
                WHERE insight_type = 'book_wisdom' AND user_id = ? AND record_key = ?
                """,
                (item.user_id, record_key),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO derived_insights (
                        id, insight_type, title, content, classification, sensitivity,
                        external_allowed, confidence, lineage_json, status, created_at,
                        updated_at, user_id, record_key, author_perspective,
                        user_perspective, vellum_perspective, explanation,
                        uncertainty_json, permitted_uses_json, valid_from, valid_to,
                        expires_at, derivation, source_agent, model_version,
                        prompt_version, policy_version, schema_version
                    ) VALUES (
                        ?, 'book_wisdom', ?, ?, ?, ?, 0, ?, '[]', 'proposed', ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        wisdom_id,
                        item.title,
                        item.content,
                        item.wisdom_type,
                        item.sensitivity.value,
                        float(item.confidence),
                        now,
                        now,
                        item.user_id,
                        record_key,
                        item.author_perspective,
                        item.user_perspective,
                        item.vellum_perspective,
                        item.explanation,
                        _json(item.uncertainty),
                        _json(item.permitted_uses),
                        _iso(item.valid_from),
                        _iso(item.valid_to),
                        _iso(item.expires_at),
                        item.derivation,
                        item.source_agent,
                        item.model_version,
                        item.prompt_version,
                        item.policy_version,
                        item.schema_version,
                    ),
                )
                lifecycle = "proposed"
            else:
                wisdom_id = str(existing["id"])
                lifecycle = str(existing["status"])

            evidence_added = 0
            for reference in unique_evidence.values():
                evidence_id = _stable_id(
                    "wie",
                    wisdom_id,
                    reference.kind,
                    reference.reference_id,
                    reference.stance,
                )
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO derived_insight_evidence (
                        id, insight_id, kind, reference_id, stance, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence_id,
                        wisdom_id,
                        reference.kind,
                        reference.reference_id,
                        reference.stance,
                        now,
                    ),
                )
                evidence_added += int(cursor.rowcount) > 0
            evidence_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM derived_insight_evidence WHERE insight_id = ?",
                    (wisdom_id,),
                ).fetchone()[0]
            )
        return {
            "wisdom_id": wisdom_id,
            "created": existing is None,
            "lifecycle": lifecycle,
            "evidence_added": evidence_added,
            "evidence_count": evidence_count,
        }

    def get_book_wisdom_record(
        self,
        *,
        user_id: str,
        wisdom_id: str,
    ) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM derived_insights
                WHERE id = ? AND user_id = ? AND insight_type = 'book_wisdom'
                """,
                (wisdom_id, user_id),
            ).fetchone()
            if row is None:
                return None
            evidence = connection.execute(
                """
                SELECT kind, reference_id, stance
                FROM derived_insight_evidence
                WHERE insight_id = ?
                ORDER BY stance, kind, reference_id
                """,
                (wisdom_id,),
            ).fetchall()
        result = dict(row)
        result["external_allowed"] = bool(result["external_allowed"])
        result["lineage"] = json.loads(str(result.pop("lineage_json") or "[]"))
        result["uncertainty"] = json.loads(str(result.pop("uncertainty_json") or "[]"))
        result["permitted_uses"] = json.loads(str(result.pop("permitted_uses_json") or "[]"))
        result["evidence"] = [dict(item) for item in evidence]
        return result

    def list_observation_details(
        self,
        *,
        origin: str = "",
        action: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if origin:
            clauses.append("origin = ?")
            params.append(origin)
        if action:
            clauses.append("action = ?")
            params.append(action)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT id, event_key, origin, actor, trigger, action, source_id,
                       payload_json, sensitivity, confidence, observed_at,
                       expires_at, promotion_status
                FROM observations {where}
                ORDER BY observed_at DESC LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["payload"] = json.loads(str(record.pop("payload_json") or "{}"))
            records.append(record)
        return records

    def list_observation_details_after_rowid(
        self,
        *,
        origin: str = "",
        actions: Iterable[str] = (),
        after_rowid: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read immutable observations in insertion order for resumable projections."""
        clauses: list[str] = ["rowid > ?"]
        params: list[Any] = [max(0, int(after_rowid))]
        if origin:
            clauses.append("origin = ?")
            params.append(origin)
        clean_actions = list(dict.fromkeys(str(action) for action in actions if str(action)))
        if clean_actions:
            placeholders = ", ".join("?" for _ in clean_actions)
            clauses.append(f"action IN ({placeholders})")
            params.extend(clean_actions)
        params.append(max(1, min(int(limit), 500)))
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT rowid AS observation_rowid, id, event_key, origin, actor,
                       trigger, action, source_id, payload_json, sensitivity,
                       confidence, observed_at, expires_at, promotion_status
                FROM observations
                WHERE {" AND ".join(clauses)}
                ORDER BY rowid ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["payload"] = json.loads(str(record.pop("payload_json") or "{}"))
            records.append(record)
        return records

    def register_projection(self, item: ProjectionInput) -> dict[str, Any]:
        projection_id = _stable_id("prj", item.target, item.target_ref)
        now = _now()
        with closing(self._connect()) as connection, connection:
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

    def list_projections(
        self,
        *,
        target: str = "",
        target_ref: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        clauses = []
        if target:
            clauses.append("target = ?")
            params.append(target)
        if target_ref:
            clauses.append("target_ref = ?")
            params.append(target_ref)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                SELECT id, canonical_type, canonical_id, target, target_ref,
                       projection_type, content_hash, generated_by, do_not_reingest,
                       metadata_json, last_exported_at
                FROM projections {where}
                ORDER BY target, target_ref LIMIT ?
                """,
                params,
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["do_not_reingest"] = bool(item["do_not_reingest"])
            item["metadata"] = json.loads(str(item.pop("metadata_json") or "{}"))
            items.append(item)
        return items

    def record_user_signal(self, item: UserSignalInput) -> dict[str, Any]:
        signal_id = _stable_id("sig", item.event_key)
        observed_at = _iso(item.observed_at) or _now()
        eligible_actor = item.actor not in {ObservationActor.AGENT, ObservationActor.SCHEDULED}
        eligible = bool(item.preference_evidence and eligible_actor)
        effective_weight = min(float(item.weight), _EVIDENCE_WEIGHT_CAPS[item.evidence_class.value])
        now = _now()
        with closing(self._connect()) as connection, connection:
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
                        effective_weight,
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
            "effective_weight": effective_weight,
            "preference": state,
        }

    def record_user_signals(
        self,
        items: Iterable[UserSignalInput],
        *,
        recompute: bool = True,
        now: datetime | None = None,
    ) -> dict[str, int]:
        created = 0
        existing_count = 0
        subject_keys: set[str] = set()
        with closing(self._connect()) as connection, connection:
            for item in items:
                signal_id = _stable_id("sig", item.event_key)
                observed_at = _iso(item.observed_at) or _now()
                eligible_actor = item.actor not in {ObservationActor.AGENT, ObservationActor.SCHEDULED}
                eligible = bool(item.preference_evidence and eligible_actor)
                effective_weight = min(float(item.weight), _EVIDENCE_WEIGHT_CAPS[item.evidence_class.value])
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO user_signals (
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
                        effective_weight,
                        item.actor.value,
                        item.source_id,
                        item.observation_id,
                        observed_at,
                        _json(item.metadata),
                        _now(),
                        item.subject_key,
                        item.category,
                        item.evidence_class.value,
                        int(eligible),
                        item.event_key,
                        item.sensitivity.value,
                    ),
                )
                subject_keys.add(item.subject_key)
                if int(cursor.rowcount) > 0:
                    created += 1
                else:
                    existing_count += 1

        recomputed = len(self.recompute_preferences(subject_keys, now=now)) if recompute else 0
        return {
            "created": created,
            "existing": existing_count,
            "subjects_recomputed": recomputed,
        }

    def prune_user_signals(
        self,
        *,
        event_key_prefix: str,
        categories: Iterable[str],
        keep_event_keys: Iterable[str],
    ) -> dict[str, Any]:
        """Remove derived signals in one owned namespace that are no longer canonical."""
        prefix = str(event_key_prefix).strip()
        if not prefix or "%" in prefix or "_" in prefix:
            raise ValueError("event_key_prefix must be a non-empty literal prefix")
        owned_categories = sorted({str(category).strip() for category in categories if str(category).strip()})
        if not owned_categories:
            raise ValueError("categories cannot be empty")
        keep = {str(event_key) for event_key in keep_event_keys if str(event_key)}
        placeholders = ", ".join("?" for _ in owned_categories)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                SELECT id, event_key, subject_key
                FROM user_signals
                WHERE event_key LIKE ? AND category IN ({placeholders})
                """,
                [f"{prefix}%", *owned_categories],
            ).fetchall()
            stale = [row for row in rows if str(row["event_key"]) not in keep]
            for offset in range(0, len(stale), 400):
                batch = stale[offset:offset + 400]
                ids = [str(row["id"]) for row in batch]
                id_placeholders = ", ".join("?" for _ in ids)
                connection.execute(
                    f"DELETE FROM user_signals WHERE id IN ({id_placeholders})",
                    ids,
                )
        return {
            "removed": len(stale),
            "subject_keys": sorted({str(row["subject_key"]) for row in stale}),
        }

    def prune_user_signals_against_observations(
        self,
        *,
        event_key_prefix: str,
        categories: Iterable[str],
        origin: str,
        actions: Iterable[str],
    ) -> dict[str, Any]:
        """Remove owned derived signals whose canonical observations no longer exist."""
        prefix = str(event_key_prefix).strip()
        if not prefix or "%" in prefix or "_" in prefix:
            raise ValueError("event_key_prefix must be a non-empty literal prefix")
        owned_categories = sorted(
            {str(category).strip() for category in categories if str(category).strip()}
        )
        clean_actions = sorted(
            {str(action).strip() for action in actions if str(action).strip()}
        )
        if not owned_categories or not origin or not clean_actions:
            raise ValueError("origin, actions, and categories are required")
        category_placeholders = ", ".join("?" for _ in owned_categories)
        action_placeholders = ", ".join("?" for _ in clean_actions)
        with closing(self._connect()) as connection, connection:
            stale = connection.execute(
                f"""
                SELECT signals.id, signals.subject_key
                FROM user_signals signals
                WHERE signals.event_key LIKE ?
                  AND signals.category IN ({category_placeholders})
                  AND (
                      signals.observation_id IS NULL
                      OR NOT EXISTS (
                          SELECT 1
                          FROM observations observations
                          WHERE observations.id = signals.observation_id
                            AND observations.origin = ?
                            AND observations.action IN ({action_placeholders})
                      )
                  )
                """,
                [f"{prefix}%", *owned_categories, origin, *clean_actions],
            ).fetchall()
            for offset in range(0, len(stale), 400):
                batch = stale[offset:offset + 400]
                ids = [str(row["id"]) for row in batch]
                placeholders = ", ".join("?" for _ in ids)
                connection.execute(
                    f"DELETE FROM user_signals WHERE id IN ({placeholders})",
                    ids,
                )
        return {
            "removed": len(stale),
            "subject_keys": sorted({str(row["subject_key"]) for row in stale}),
        }

    def list_user_signal_subject_keys(
        self,
        *,
        event_key_prefix: str,
        categories: Iterable[str],
    ) -> list[str]:
        prefix = str(event_key_prefix).strip()
        owned_categories = sorted(
            {str(category).strip() for category in categories if str(category).strip()}
        )
        if not prefix or "%" in prefix or "_" in prefix or not owned_categories:
            raise ValueError("event_key_prefix and categories are required")
        placeholders = ", ".join("?" for _ in owned_categories)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT subject_key
                FROM user_signals
                WHERE event_key LIKE ? AND category IN ({placeholders})
                ORDER BY subject_key ASC
                """,
                [f"{prefix}%", *owned_categories],
            ).fetchall()
        return [str(row["subject_key"]) for row in rows]

    def upsert_content_annotation(
        self,
        item: ContentAnnotationInput,
        *,
        trusted_user_review: bool = False,
    ) -> dict[str, Any]:
        labels = set(item.labels)
        sensitive = bool(labels & _SENSITIVE_LABELS)
        reviewed = bool(trusted_user_review)
        eligible_for_preference = bool(item.eligible_for_preference and (reviewed or not sensitive))
        eligible_for_style = bool(
            item.eligible_for_style
            and (reviewed or not sensitive)
            and item.stance.value != "unknown"
        )
        requires_review = bool(sensitive and not reviewed)
        annotation_id = _stable_id("ann", item.target_type, item.target_id, item.taxonomy_version)
        now = _now()
        with closing(self._connect()) as connection, connection:
            existing = connection.execute(
                "SELECT id FROM content_annotations WHERE id = ?",
                (annotation_id,),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO content_annotations (
                    id, target_type, target_id, taxonomy_version, labels_json,
                    context, stance, intent, confidence, eligible_for_preference,
                    eligible_for_style, requires_review, metadata_json, created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    labels_json = excluded.labels_json,
                    context = excluded.context,
                    stance = excluded.stance,
                    intent = excluded.intent,
                    confidence = excluded.confidence,
                    eligible_for_preference = excluded.eligible_for_preference,
                    eligible_for_style = excluded.eligible_for_style,
                    requires_review = excluded.requires_review,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    annotation_id,
                    item.target_type,
                    item.target_id,
                    item.taxonomy_version,
                    _json(sorted(labels)),
                    item.context,
                    item.stance.value,
                    item.intent,
                    float(item.confidence),
                    int(eligible_for_preference),
                    int(eligible_for_style),
                    int(requires_review),
                    _json(item.metadata),
                    now,
                    now,
                ),
            )
            row = connection.execute("SELECT * FROM content_annotations WHERE id = ?", (annotation_id,)).fetchone()
        return {**self._annotation_row(row), "created": existing is None}

    def list_content_annotations(
        self,
        *,
        target_id: str = "",
        requires_review: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if target_id:
            clauses.append("target_id = ?")
            params.append(target_id)
        if requires_review is not None:
            clauses.append("requires_review = ?")
            params.append(int(requires_review))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"SELECT * FROM content_annotations {where} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._annotation_row(row) for row in rows]

    @staticmethod
    def _annotation_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["labels"] = json.loads(str(item.pop("labels_json") or "[]"))
        item["metadata"] = json.loads(str(item.pop("metadata_json") or "{}"))
        item["eligible_for_preference"] = bool(item["eligible_for_preference"])
        item["eligible_for_style"] = bool(item["eligible_for_style"])
        item["requires_review"] = bool(item["requires_review"])
        return item

    def recompute_preference(self, subject_key: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        return self.recompute_preferences((subject_key,), now=now).get(subject_key)

    def get_preference(self, subject_key: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM preference_states WHERE subject_key = ?",
                (subject_key,),
            ).fetchone()
        return self._preference_row(row) if row is not None else None

    def recompute_preferences(
        self,
        subject_keys: Iterable[str],
        *,
        now: datetime | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Recompute many states with one read/write transaction per bounded batch."""
        keys = list(dict.fromkeys(str(key) for key in subject_keys if str(key)))
        if not keys:
            return {}
        reference = now or datetime.now(UTC)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        results: dict[str, dict[str, Any]] = {}
        updated_at = _now()
        for offset in range(0, len(keys), 500):
            chunk = keys[offset:offset + 500]
            placeholders = ", ".join("?" for _ in chunk)
            with closing(self._connect()) as connection, connection:
                rows = connection.execute(
                    f"""
                    SELECT subject_key, value, weight, observed_at, category,
                           signal_type, evidence_class
                    FROM user_signals
                    WHERE eligible = 1 AND subject_key IN ({placeholders})
                    ORDER BY subject_key ASC, observed_at ASC
                    """,
                    chunk,
                ).fetchall()
                grouped: dict[str, list[sqlite3.Row]] = {key: [] for key in chunk}
                for row in rows:
                    grouped[str(row["subject_key"])].append(row)
                for key in chunk:
                    state = _build_preference_state(key, grouped[key], reference)
                    if state is None:
                        connection.execute(
                            "DELETE FROM preference_states WHERE subject_key = ?",
                            (key,),
                        )
                        continue
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
                            _stable_id("pref", key),
                            key,
                            state["category"],
                            state["current_score"],
                            state["trend"],
                            state["lifecycle"],
                            state["confidence"],
                            state["historical_peak"],
                            _json(state["windows"]),
                            state["evidence_count"],
                            state["last_meaningful_engagement"],
                            updated_at,
                        ),
                    )
                    row = connection.execute(
                        "SELECT * FROM preference_states WHERE subject_key = ?",
                        (key,),
                    ).fetchone()
                    if row is not None:
                        results[key] = self._preference_row(row)
        return results

    def count_preferences(self, *, category: str = "", min_evidence_count: int = 0) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if min_evidence_count > 0:
            clauses.append("evidence_count >= ?")
            params.append(int(min_evidence_count))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS total FROM preference_states {where}",
                params,
            ).fetchone()
        return int(row["total"] if row is not None else 0)

    def list_preferences(self, *, category: str = "", limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if category:
            where = "WHERE category = ?"
            params.append(category)
        params.append(max(1, min(int(limit), 500)))
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"SELECT * FROM preference_states {where} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._preference_row(row) for row in rows]

    def list_ranked_preferences(
        self,
        *,
        category: str,
        limit: int = 100,
        trend: str = "",
        min_evidence_count: int = 0,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 500))
        clauses = ["category = ?"]
        params: list[Any] = [category]
        if trend:
            clauses.append("trend = ?")
            params.append(trend)
        if min_evidence_count > 0:
            clauses.append("evidence_count >= ?")
            params.append(int(min_evidence_count))
        params.append(bounded_limit)
        order = (
            "evidence_count DESC, confidence DESC, current_score DESC"
            if trend == "falling"
            else "current_score DESC, confidence DESC, evidence_count DESC"
        )
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM preference_states
                WHERE {" AND ".join(clauses)}
                ORDER BY {order}
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._preference_row(row) for row in rows]

    def preferences_for_subjects(
        self,
        subject_keys: Iterable[str],
    ) -> list[dict[str, Any]]:
        keys = list(dict.fromkeys(str(key) for key in subject_keys if str(key)))
        if not keys:
            return []
        if len(keys) > 500:
            raise ValueError("preferences_for_subjects accepts at most 500 subject keys")
        placeholders = ", ".join("?" for _ in keys)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"SELECT * FROM preference_states WHERE subject_key IN ({placeholders})",
                keys,
            ).fetchall()
        return [self._preference_row(row) for row in rows]

    def search_latest_signal_metadata(
        self,
        *,
        category: str,
        query_terms: Iterable[str],
        limit: int = 100,
    ) -> dict[str, dict[str, Any]]:
        terms = list(
            dict.fromkeys(
                str(term).casefold().strip()
                for term in query_terms
                if str(term).strip()
            )
        )
        if not terms:
            return {}
        bounded_limit = max(1, min(int(limit), 500))
        filters = " AND ".join("LOWER(metadata_json) LIKE ?" for _ in terms)
        params: list[Any] = [category]
        params.extend(f"%{term}%" for term in terms)
        params.append(bounded_limit)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                SELECT subject_key, observed_at, metadata_json
                FROM (
                    SELECT
                        subject_key,
                        observed_at,
                        metadata_json,
                        ROW_NUMBER() OVER (
                            PARTITION BY subject_key
                            ORDER BY observed_at DESC, id DESC
                        ) AS row_number
                    FROM user_signals
                    WHERE category = ? AND eligible = 1 AND {filters}
                )
                WHERE row_number = 1
                ORDER BY observed_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return {
            str(row["subject_key"]): {
                "observed_at": str(row["observed_at"] or ""),
                "metadata": json.loads(str(row["metadata_json"] or "{}")),
            }
            for row in rows
        }

    def latest_signal_metadata(
        self,
        subject_keys: Iterable[str],
    ) -> dict[str, dict[str, Any]]:
        keys = list(dict.fromkeys(str(key) for key in subject_keys if str(key)))
        if not keys:
            return {}
        if len(keys) > 500:
            raise ValueError("latest_signal_metadata accepts at most 500 subject keys")
        placeholders = ", ".join("?" for _ in keys)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                SELECT subject_key, observed_at, metadata_json
                FROM user_signals
                WHERE eligible = 1 AND subject_key IN ({placeholders})
                ORDER BY subject_key ASC, observed_at DESC, id DESC
                """,
                keys,
            ).fetchall()
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            subject_key = str(row["subject_key"])
            if subject_key in latest:
                continue
            latest[subject_key] = {
                "observed_at": str(row["observed_at"] or ""),
                "metadata": json.loads(str(row["metadata_json"] or "{}")),
            }
        return latest

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
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
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
        expected_attempt: int | None = None,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._complete_ingestion_job(
                connection,
                job_id,
                stats=stats,
                cursor=cursor,
                expected_attempt=expected_attempt,
            )

    def _complete_ingestion_job(
        self, connection: sqlite3.Connection, job_id: str, *,
        stats: dict[str, Any] | None = None, cursor: SyncCursorInput | None = None,
        expected_attempt: int | None = None,
    ) -> dict[str, Any]:
        now = _now()
        row = connection.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown ingestion job: {job_id}")
        if expected_attempt is not None:
            self._assert_ingestion_job_claim(row, expected_attempt)
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

    @staticmethod
    def _assert_ingestion_job_claim(row: sqlite3.Row, expected_attempt: int) -> None:
        if (
            row["status"] != "running"
            or int(row["attempt_count"]) != expected_attempt
            or KnowledgeStore._timestamp_expired(str(row["lease_expires_at"]), datetime.now(UTC))
        ):
            raise IngestionJobLeaseLost("INGESTION_LEASE_LOST")

    def fail_ingestion_job(
        self, job_id: str, *, error_code: str, expected_attempt: int | None = None,
    ) -> dict[str, Any]:
        safe_code = "".join(character for character in error_code.upper() if character.isalnum() or character == "_")[:80]
        safe_code = safe_code or "INGESTION_FAILED"
        now = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown ingestion job: {job_id}")
            if expected_attempt is not None:
                self._assert_ingestion_job_claim(row, expected_attempt)
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

    def save_sync_cursor(
        self,
        item: SyncCursorInput,
        *,
        succeeded_at: datetime | None = None,
    ) -> dict[str, Any]:
        saved_at = _iso(succeeded_at) or _now()
        with closing(self._connect()) as connection, connection:
            self._upsert_sync_cursor(connection, item, succeeded_at=saved_at)
            row = connection.execute(
                "SELECT * FROM sync_cursors WHERE connector = ? AND account_id = ?",
                (item.connector, item.account_id),
            ).fetchone()
        return self._cursor_row(row)

    def get_sync_cursor(self, connector: str, account_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection, connection:
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
        with closing(self._connect()) as connection, connection:
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
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"SELECT * FROM ingestion_jobs {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._job_row(row) for row in rows]

    def heartbeat_ingestion_job(self, job_id: str, *, lease_seconds: int = 900) -> dict[str, Any]:
        bounded_lease = max(30, min(int(lease_seconds), 86400))
        lease_expires_at = (datetime.now(UTC) + timedelta(seconds=bounded_lease)).isoformat()
        with closing(self._connect()) as connection, connection:
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
        with closing(self._connect()) as connection, connection:
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

    def set_source_status(self, source_id: str, status: str) -> bool:
        clean_source_id = source_id.strip()
        clean_status = status.strip()
        if not clean_source_id or not clean_status:
            raise ValueError("Source ID and status are required.")
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE sources SET status = ?, updated_at = ? WHERE id = ?",
                (clean_status, _now(), clean_source_id),
            )
        return int(cursor.rowcount) > 0

    def list_observations(self, *, origin: str = "", limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if origin:
            where = "WHERE origin = ?"
            params.append(origin)
        params.append(max(1, min(int(limit), 500)))
        with closing(self._connect()) as connection, connection:
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
        with closing(self._connect()) as connection, connection:
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
        with closing(self._connect()) as connection, connection:
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

    def publish_book_discovery_candidates(
        self, *, user_id: str, objective: str, job_id: str,
        candidates: list[dict[str, Any]], ttl_days: int, capacity: int, stats: dict[str, Any],
        expected_attempt: int,
    ) -> list[dict[str, Any]]:
        tenant = self.book_tenant_scope(user_id)
        if objective not in {"user_discovery", "vellum_exploration"}:
            raise ValueError("Invalid Discovery objective")
        if not 1 <= ttl_days <= 90 or not 1 <= capacity <= 1000 or len(candidates) > 20:
            raise ValueError("Invalid Discovery budget")
        now = _now()
        expires = (datetime.fromisoformat(now) + timedelta(days=ttl_days)).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,),
            ).fetchone()
            if job is None or job["connector"] != "books.discovery" or job["account_id"] != tenant:
                raise ValueError("Discovery job scope mismatch")
            self._assert_ingestion_job_claim(job, expected_attempt)
            # Expired catalog hints are disposable; dismissal fingerprints are not.
            connection.execute(
                "DELETE FROM book_discovery_candidates WHERE tenant_scope = ? AND state != 'dismissed' AND expires_at <= ?",
                (tenant, now),
            )
            for item in candidates:
                payload = _json(item)
                if len(payload.encode("utf-8")) > 16384:
                    raise ValueError("Discovery metadata budget exceeded")
                blocked = connection.execute(
                    """SELECT 1 FROM book_discovery_candidates
                       WHERE tenant_scope = ? AND state = 'dismissed'
                         AND (work_id = ? OR identity_hash = ?)""",
                    (tenant, item["work_id"], item["identity_hash"]),
                ).fetchone()
                if blocked:
                    continue
                matches = connection.execute(
                    """SELECT id, state, expires_at FROM book_discovery_candidates
                       WHERE tenant_scope = ? AND objective = ?
                         AND (work_id = ? OR identity_hash = ?)""",
                    (tenant, objective, item["work_id"], item["identity_hash"]),
                ).fetchall()
                if len(matches) > 1:
                    # Conflicting catalog identities need later verification, not a silent merge.
                    continue
                if matches:
                    existing = matches[0]
                    if existing["state"] == "verified" and existing["expires_at"] > now:
                        continue
                    # Preserve the candidate ID and first-discovery time across refreshes.
                    connection.execute(
                        """UPDATE book_discovery_candidates
                           SET metadata_json = ?, relevance_score = ?, job_id = ?, work_id = ?, identity_hash = ?,
                               checked_at = ?, expires_at = ?, state = 'discovered'
                           WHERE id = ?""",
                        (payload, item["relevance_score"], job_id, item["work_id"], item["identity_hash"],
                         now, expires, existing["id"]),
                    )
                    continue
                count = connection.execute(
                    "SELECT COUNT(*) FROM book_discovery_candidates WHERE tenant_scope = ?", (tenant,),
                ).fetchone()[0]
                if count >= capacity:
                    continue
                candidate_id = _stable_id("book-discovery", tenant, objective, item["identity_hash"], job_id)
                connection.execute(
                    """INSERT INTO book_discovery_candidates
                       (id, tenant_scope, objective, work_id, identity_hash, state,
                        metadata_json, relevance_score, job_id, discovered_at, checked_at, expires_at)
                       VALUES (?, ?, ?, ?, ?, 'discovered', ?, ?, ?, ?, ?, ?)""",
                    (candidate_id, tenant, objective, item["work_id"], item["identity_hash"],
                     payload, item["relevance_score"], job_id, now, now, expires),
                )
            count = connection.execute(
                "SELECT COUNT(*) FROM book_discovery_candidates WHERE job_id = ? AND state = 'discovered'",
                (job_id,),
            ).fetchone()[0]
            self._complete_ingestion_job(
                connection, job_id, stats={**stats, "candidate_count": count}, expected_attempt=expected_attempt,
            )
        return self.list_book_discovery_candidates(user_id=user_id, objective=objective, job_id=job_id)

    @staticmethod
    def _book_discovery_candidate_revision(row: sqlite3.Row) -> str:
        material = [
            str(row["id"]),
            str(row["state"]),
            str(row["work_id"]),
            str(row["identity_hash"]),
            str(row["metadata_json"]),
            str(row["job_id"]),
            str(row["checked_at"]),
            str(row["expires_at"]),
        ]
        return hashlib.sha256(_json(material).encode("utf-8")).hexdigest()

    @classmethod
    def _book_discovery_candidate_row(
        cls, row: sqlite3.Row, *, include_internal: bool = False,
    ) -> dict[str, Any] | None:
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except (TypeError, ValueError, RecursionError):
            return None
        if not isinstance(metadata, dict):
            return None
        item = {
            **metadata,
            "candidate_id": str(row["id"]),
            "objective": str(row["objective"]),
            "state": str(row["state"]),
            "mode": "shadow",
            "checked_at": str(row["checked_at"]),
            "expires_at": str(row["expires_at"]),
        }
        if include_internal:
            item["_candidate_revision"] = cls._book_discovery_candidate_revision(row)
        return item

    def get_book_discovery_candidate(
        self, *, user_id: str, candidate_id: str, include_internal: bool = False,
    ) -> dict[str, Any] | None:
        if not re.fullmatch(r"book-discovery_[0-9a-f]{32}", candidate_id or ""):
            return None
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM book_discovery_candidates WHERE id = ? AND tenant_scope = ?",
                (candidate_id, self.book_tenant_scope(user_id)),
            ).fetchone()
        return self._book_discovery_candidate_row(row, include_internal=include_internal) if row else None

    def publish_book_discovery_verification(
        self,
        *,
        user_id: str,
        candidate_id: str,
        expected_revision: str,
        job_id: str,
        expected_attempt: int,
        verification_metadata: dict[str, Any],
        stats: dict[str, Any],
        verified: bool = True,
    ) -> dict[str, Any]:
        tenant = self.book_tenant_scope(user_id)
        if not re.fullmatch(r"book-discovery_[0-9a-f]{32}", candidate_id or ""):
            raise BookDiscoveryCandidateChanged("DISCOVERY_CANDIDATE_CHANGED")
        if not isinstance(verification_metadata, dict):
            raise ValueError("Invalid Discovery verification metadata")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
            if (job is None or job["connector"] != "books.discovery" or job["account_id"] != tenant
                    or job["job_type"] != "metadata_verification"):
                raise ValueError("Discovery verification job scope mismatch")
            self._assert_ingestion_job_claim(job, expected_attempt)
            row = connection.execute(
                "SELECT * FROM book_discovery_candidates WHERE id = ? AND tenant_scope = ?",
                (candidate_id, tenant),
            ).fetchone()
            if row is None or row["state"] != "discovered":
                raise BookDiscoveryCandidateChanged("DISCOVERY_CANDIDATE_CHANGED")
            if self._book_discovery_candidate_revision(row) != expected_revision:
                raise BookDiscoveryCandidateChanged("DISCOVERY_CANDIDATE_CHANGED")
            now = _now()
            reference = _parse_datetime(now) or datetime.now(UTC)
            if self._timestamp_expired(str(row["expires_at"]), reference):
                raise BookDiscoveryCandidateChanged("DISCOVERY_CANDIDATE_EXPIRED")
            try:
                existing_metadata = json.loads(str(row["metadata_json"] or "{}"))
            except (TypeError, ValueError, RecursionError):
                raise BookDiscoveryCandidateChanged("DISCOVERY_CANDIDATE_CHANGED") from None
            if not isinstance(existing_metadata, dict):
                raise BookDiscoveryCandidateChanged("DISCOVERY_CANDIDATE_CHANGED")
            merged = {
                **existing_metadata,
                "verification": "verified" if verified else "unverified",
                "verification_metadata": verification_metadata,
                "metadata_trust": "catalog_records_cross_checked" if verified else "catalog_record",
                "content_available": False,
            }
            if verified:
                merged["cover_url"] = verification_metadata.get("provenance", {}).get("cover_url", "")
                merged["cover_id"] = verification_metadata.get("cover_id")
                merged["cover_status"] = verification_metadata.get("cover_status", "unavailable")
            payload = _json(merged)
            if len(payload.encode("utf-8")) > 16384:
                raise ValueError("Discovery metadata budget exceeded")
            connection.execute(
                """
                UPDATE book_discovery_candidates
                SET state = ?, metadata_json = ?, checked_at = ?
                WHERE id = ? AND tenant_scope = ? AND state = 'discovered'
                """,
                ("verified" if verified else "discovered", payload, now, candidate_id, tenant),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise BookDiscoveryCandidateChanged("DISCOVERY_CANDIDATE_CHANGED")
            self._complete_ingestion_job(
                connection,
                job_id,
                stats={**stats, "verification": "verified" if verified else "unverified"},
                expected_attempt=expected_attempt,
            )
            verified = connection.execute(
                "SELECT * FROM book_discovery_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
        result = self._book_discovery_candidate_row(verified)
        if result is None:
            raise ValueError("Invalid Discovery candidate metadata")
        return result

    def list_book_discovery_candidates(
        self, *, user_id: str, objective: str, job_id: str = "", limit: int = 20,
    ) -> list[dict[str, Any]]:
        if objective not in {"user_discovery", "vellum_exploration"}:
            raise ValueError("Invalid Discovery objective")
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """SELECT * FROM book_discovery_candidates
                   WHERE tenant_scope = ? AND objective = ? AND state IN ('discovered', 'verified')
                     AND expires_at > ? AND (? = '' OR job_id = ?)
                   ORDER BY relevance_score DESC, work_id ASC LIMIT ?""",
                (self.book_tenant_scope(user_id), objective, _now(), job_id, job_id, min(max(limit, 1), 100)),
            ).fetchall()
        return [
            {**json.loads(row["metadata_json"]), "candidate_id": row["id"],
             "objective": row["objective"], "state": row["state"], "mode": "shadow",
             "checked_at": row["checked_at"], "expires_at": row["expires_at"]}
            for row in rows
        ]

    def dismiss_book_discovery_candidate(self, *, user_id: str, candidate_id: str) -> bool:
        tenant = self.book_tenant_scope(user_id)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT work_id, identity_hash FROM book_discovery_candidates WHERE id = ? AND tenant_scope = ?",
                (candidate_id, tenant),
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                """UPDATE book_discovery_candidates SET state = 'dismissed', metadata_json = '{}',
                       relevance_score = 0
                   WHERE tenant_scope = ? AND (work_id = ? OR identity_hash = ?)""",
                (tenant, row["work_id"], row["identity_hash"]),
            )
        return True

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
            "derived_insight_evidence",
            "projections",
            "sync_cursors",
            "ingestion_jobs",
            "context_packs",
            "content_annotations",
            "book_assets",
            "user_book_imports",
            "book_ingestion_runs",
            "book_stage_receipts",
            "book_documents",
            "book_document_resources",
            "book_quality_assessments",
            "book_materializations",
            "active_book_materializations",
            "book_materialization_candidates",
            "user_learning_candidates",
            "user_learning_candidate_evidence",
            "book_discovery_candidates",
        )
        with closing(self._connect()) as connection, connection:
            counts = {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        return {
            "ready": True,
            "schema_version": version,
            "storage": "embedded_sqlite",
            "blobs": "local_content_addressed_gzip",
            "counts": counts,
        }

    def backup_database(self, destination: str | Path) -> None:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as source, closing(sqlite3.connect(target)) as backup:
            source.backup(backup)

    def integrity_check(self) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            result = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_key_errors = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]
        return {
            "ok": result.casefold() == "ok" and not foreign_key_errors,
            "sqlite": result,
            "foreign_key_errors": len(foreign_key_errors),
        }
