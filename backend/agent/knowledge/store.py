"""SQLite-backed canonical evidence store for Vellum Personal Intelligence.

The store is deliberately local-first and dependency-light. Large source bodies
are content-addressed and gzip-compressed outside SQLite; the database owns
identity, provenance, lineage, policy, and temporal state.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from agent.knowledge.models import ContextPackRequest, ObservationInput, ProjectionInput, SourceItemInput
from agent.privacy.scrubber import PrivacyScrubber


SCHEMA_VERSION = 1


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
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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
