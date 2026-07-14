from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Sequence
import unicodedata

from agent.skills.parser import SkillPackageError, SkillPackageParser


CATALOG_SCHEMA_VERSION = 2
DEFAULT_SEMANTIC_THRESHOLD = 0.92
EMBEDDING_MODEL = "BAAI/bge-m3"


class SkillCatalogError(ValueError):
    pass


class SkillTextNormalizer:
    _BIDI = {"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI"}

    @classmethod
    def normalize(cls, value: str) -> str:
        text = unicodedata.normalize("NFKC", value)
        if any(unicodedata.bidirectional(character) in cls._BIDI for character in text):
            raise SkillCatalogError("bidirectional control characters are forbidden in skill text")
        text = "".join(
            character
            for character in text
            if not (unicodedata.category(character) == "Cf" or character in {"\u200b", "\u200c", "\u200d", "\ufeff"})
        )
        return " ".join(text.split())

    @classmethod
    def identity(cls, value: str) -> str:
        return cls.normalize(value).casefold()

    @classmethod
    def detector_view(cls, value: str) -> str:
        return cls.normalize(value).casefold()


def package_content_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def semantic_projection(description: str, body: str) -> str:
    sections = []
    current: list[str] = []
    keep = False
    for line in body.splitlines():
        if line.startswith("## "):
            if keep and current:
                sections.extend(current)
            heading = line[3:].strip().casefold()
            keep = heading in {"when to use", "procedure"}
            current = [line] if keep else []
        elif keep:
            current.append(line)
    if keep and current:
        sections.extend(current)
    selected = "\n".join(sections).strip() or body.strip()
    return SkillTextNormalizer.normalize(f"{description}\n{selected}")


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


def calibrate_semantic_threshold(
    labeled_scores: Sequence[tuple[float, bool]], *, min_precision: float = 0.95, min_recall: float = 0.85
) -> dict[str, Any]:
    if len(labeled_scores) < 200:
        raise SkillCatalogError("semantic calibration requires at least 200 labeled cases")
    best = None
    for threshold in sorted({score for score, _label in labeled_scores}, reverse=True):
        true_positive = sum(score >= threshold and label for score, label in labeled_scores)
        false_positive = sum(score >= threshold and not label for score, label in labeled_scores)
        false_negative = sum(score < threshold and label for score, label in labeled_scores)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        if precision >= min_precision and recall >= min_recall:
            candidate = {"threshold": threshold, "precision": precision, "recall": recall}
            if best is None or candidate["recall"] > best["recall"]:
                best = candidate
    if best is None:
        raise SkillCatalogError("no semantic threshold satisfies the production precision and recall gates")
    return {**best, "cases": len(labeled_scores), "model": EMBEDDING_MODEL, "projection_version": 1}


@dataclass(frozen=True)
class CatalogReconcileReport:
    indexed: int
    removed: int
    unchanged_embeddings: int
    recomputed_embeddings: int
    duplicate_candidates: int
    errors: tuple[str, ...] = ()


class SkillCatalog:
    def __init__(
        self,
        root: str | Path,
        *,
        db_path: str | Path | None = None,
        embedder: Callable[[str], list[float]] | None = None,
        semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
    ):
        self.root = Path(root).resolve()
        self.path = Path(db_path) if db_path else self.root.parent / "data" / "skills" / "catalog.db"
        self.embedder = embedder
        self.semantic_threshold = semantic_threshold
        self.parser = SkillPackageParser()
        self._migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    def reconcile(self, *, embed_semantics: bool = True) -> CatalogReconcileReport:
        packages: list[tuple[str, Path, Any]] = []
        errors: list[str] = []
        lifecycle = [("active", self.root / "packages"), ("proposed", self.root / "proposed"), ("retired", self.root / "retired"), ("archived", self.root / ".archive")]
        seen_names: dict[str, Path] = {}
        seen_hashes: dict[str, Path] = {}
        for state, base in lifecycle:
            if not base.exists():
                continue
            for skill_file in sorted(base.rglob("SKILL.md")):
                try:
                    package = self.parser.parse(skill_file.parent, state=state, source_root=base)
                    identity = SkillTextNormalizer.identity(package.metadata.name)
                    content_hash = package_content_hash(package.root)
                    if identity in seen_names:
                        raise SkillCatalogError(f"duplicate normalized skill name {identity}: {seen_names[identity]} and {package.root}")
                    if content_hash in seen_hashes:
                        raise SkillCatalogError(f"duplicate package content: {seen_hashes[content_hash]} and {package.root}")
                    seen_names[identity] = package.root
                    seen_hashes[content_hash] = package.root
                    packages.append((state, base, package))
                except (SkillPackageError, SkillCatalogError) as exc:
                    errors.append(str(exc))
        if errors:
            raise SkillCatalogError("; ".join(errors))

        with self.connect() as connection:
            existing = {row["normalized_name"]: dict(row) for row in connection.execute("SELECT * FROM skills")}
            live_names: set[str] = set()
            unchanged = 0
            recomputed = 0
            candidates = 0
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM skills_fts")
                for state, base, package in packages:
                    name = SkillTextNormalizer.identity(package.metadata.name)
                    live_names.add(name)
                    content_hash = package_content_hash(package.root)
                    projection = semantic_projection(package.metadata.description, package.body)
                    semantic_fingerprint = hashlib.sha256(projection.encode("utf-8")).hexdigest()
                    previous = existing.get(name)
                    vector_json = previous.get("vector_json") if previous else None
                    if previous and previous.get("semantic_fingerprint") == semantic_fingerprint:
                        unchanged += 1
                    elif embed_semantics:
                        vector = self._embed(projection)
                        vector_json = json.dumps(vector, separators=(",", ":"))
                        recomputed += 1
                    metadata_json = json.dumps(package.metadata.model_dump(mode="json", exclude_none=True), sort_keys=True)
                    connection.execute(
                        """INSERT INTO skills(normalized_name, display_name, description, state, category, package_path,
                               content_hash, semantic_fingerprint, vector_json, embedding_model, metadata_json, updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                           ON CONFLICT(normalized_name) DO UPDATE SET display_name=excluded.display_name,
                               description=excluded.description, state=excluded.state, category=excluded.category,
                               package_path=excluded.package_path, content_hash=excluded.content_hash,
                               semantic_fingerprint=excluded.semantic_fingerprint, vector_json=excluded.vector_json,
                               embedding_model=excluded.embedding_model, metadata_json=excluded.metadata_json,
                               updated_at=CURRENT_TIMESTAMP""",
                        (name, package.metadata.name, package.metadata.description, state, package.metadata.metadata.hermes.category,
                         package.root.relative_to(self.root).as_posix(), content_hash, semantic_fingerprint, vector_json,
                         EMBEDDING_MODEL if vector_json else None, metadata_json),
                    )
                    row_id = connection.execute("SELECT id FROM skills WHERE normalized_name=?", (name,)).fetchone()[0]
                    connection.execute("INSERT INTO skills_fts(rowid, name, description, body) VALUES(?,?,?,?)", (row_id, name, package.metadata.description, package.body))
                removed = connection.execute(
                    f"DELETE FROM skills WHERE normalized_name NOT IN ({','.join('?' for _ in live_names)})" if live_names else "DELETE FROM skills",
                    tuple(sorted(live_names)),
                ).rowcount
                connection.execute("DELETE FROM duplicate_reviews WHERE status='candidate'")
                vector_rows = [dict(row) for row in connection.execute("SELECT normalized_name, vector_json FROM skills WHERE vector_json IS NOT NULL ORDER BY normalized_name")]
                for index, left in enumerate(vector_rows):
                    left_vector = json.loads(left["vector_json"])
                    for right in vector_rows[index + 1:]:
                        score = cosine_similarity(left_vector, json.loads(right["vector_json"]))
                        if score >= self.semantic_threshold:
                            connection.execute(
                                "INSERT OR IGNORE INTO duplicate_reviews(left_name,right_name,score,status,created_at) VALUES(?,?,?,'candidate',CURRENT_TIMESTAMP)",
                                (left["normalized_name"], right["normalized_name"], score),
                            )
                            candidates += 1
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return CatalogReconcileReport(len(packages), removed, unchanged, recomputed, candidates, tuple(errors))

    def search(self, query: str, *, state: str | None = None, limit: int = 50, offset: int = 0, after: str = "") -> list[dict[str, Any]]:
        clean = SkillTextNormalizer.normalize(query)
        with self.connect() as connection:
            if clean:
                sql = "SELECT s.* FROM skills_fts JOIN skills s ON s.id=skills_fts.rowid WHERE skills_fts MATCH ?"
                params: list[Any] = [clean]
            else:
                sql = "SELECT s.* FROM skills s WHERE 1=1"
                params = []
            if state:
                sql += " AND s.state=?"
                params.append(state)
            if after:
                sql += " AND s.normalized_name>?"
                params.append(after.casefold())
            sql += " ORDER BY s.normalized_name LIMIT ? OFFSET ?"
            params.extend([min(max(limit, 1), 200), max(offset, 0)])
            return [dict(row) for row in connection.execute(sql, params)]

    def duplicate_reviews(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM duplicate_reviews ORDER BY score DESC, left_name, right_name")]

    def record_event(
        self,
        event: str,
        skill_name: str | None,
        *,
        details: dict[str, Any] | None = None,
        event_key: str = "",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        """Append an immutable skill lifecycle event.

        The catalog is current state; this ledger remains queryable after a
        package is archived or deleted.
        """
        normalized_event = SkillTextNormalizer.identity(event).replace(" ", "_")
        normalized_name = SkillTextNormalizer.identity(skill_name) if skill_name else None
        timestamp = created_at or datetime.now(timezone.utc).isoformat()
        payload = dict(details or {})
        key = event_key.strip() or hashlib.sha256(
            json.dumps(
                {"event": normalized_event, "skill": normalized_name, "created_at": timestamp, "details": payload},
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO skill_audit(event,skill_name,details_json,created_at,event_key) VALUES(?,?,?,?,?)",
                (normalized_event, normalized_name, json.dumps(payload, sort_keys=True, default=str), timestamp, key),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM skill_audit WHERE event_key=?", (key,)).fetchone()
        return self._event_row(row)

    def events(
        self,
        *,
        since: str = "",
        until: str = "",
        event: str = "",
        skill_name: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        params: list[Any] = []
        if since:
            clauses.append("created_at>=?")
            params.append(since)
        if until:
            clauses.append("created_at<?")
            params.append(until)
        if event:
            clauses.append("event=?")
            params.append(SkillTextNormalizer.identity(event).replace(" ", "_"))
        if skill_name:
            clauses.append("skill_name=?")
            params.append(SkillTextNormalizer.identity(skill_name))
        params.append(min(max(int(limit), 1), 500))
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM skill_audit WHERE {' AND '.join(clauses)} ORDER BY created_at DESC,id DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._event_row(row) for row in rows]

    def backfill_events(self) -> int:
        """Import pre-ledger Hub audit and mutation receipts once, without duplicates."""
        imported = 0
        audit_path = self.root / ".hub" / "audit.log"
        if audit_path.is_file():
            for line_number, line in enumerate(audit_path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.record_event(
                    str(item.get("action") or "unknown"),
                    str(item.get("name") or "") or None,
                    details={"source": item.get("source"), "outcome": item.get("outcome"), "backfilled": True},
                    event_key=f"hub:{item.get('action','unknown')}:{item.get('name','')}:{item.get('timestamp','')}",
                    created_at=str(item.get("timestamp") or datetime.now(timezone.utc).isoformat()),
                )
                imported += 1
        receipts = self.root / "pending" / "receipts"
        if receipts.is_dir():
            seen: set[str] = set()
            for path in sorted(receipts.glob("*.json")):
                try:
                    receipt = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                receipt_id = str(receipt.get("id") or "")
                if not receipt_id or receipt_id in seen:
                    continue
                seen.add(receipt_id)
                result = dict(receipt.get("result") or {})
                action = str(result.get("action") or "")
                if not action or action in {"install", "update", "uninstall"}:
                    continue
                self.record_event(
                    action,
                    str(result.get("name") or "") or None,
                    details={"status": result.get("status"), "backfilled": True, "mutation_id": receipt_id},
                    event_key=f"mutation:{receipt_id}",
                    created_at=str(receipt.get("completed_at") or datetime.now(timezone.utc).isoformat()),
                )
                imported += 1
        return imported

    @staticmethod
    def _event_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        try:
            result["details"] = json.loads(result.pop("details_json") or "{}")
        except json.JSONDecodeError:
            result["details"] = {}
            result.pop("details_json", None)
        return result

    def decide_duplicate(self, review_id: int, decision: str, *, distinct_reason: str = "") -> dict[str, Any]:
        allowed = {"merge", "replace", "distinct"}
        normalized = decision.casefold().strip()
        if normalized not in allowed:
            raise SkillCatalogError("duplicate decision must be merge, replace, or distinct")
        if normalized == "distinct" and not distinct_reason.strip():
            raise SkillCatalogError("distinct duplicate decisions require a reason")
        with self.connect() as connection:
            connection.execute("UPDATE duplicate_reviews SET status=?, decision_reason=?, decided_at=CURRENT_TIMESTAMP WHERE id=?", (normalized, distinct_reason.strip(), review_id))
            if connection.total_changes != 1:
                raise SkillCatalogError(f"duplicate review not found: {review_id}")
            connection.commit()
            row = connection.execute("SELECT * FROM duplicate_reviews WHERE id=?", (review_id,)).fetchone()
            return dict(row)

    def _embed(self, text: str) -> list[float]:
        if self.embedder is not None:
            return list(self.embedder(text))
        from agent.rag.embedder import get_embedder

        return get_embedder().embed(text)

    def _migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > CATALOG_SCHEMA_VERSION:
                raise SkillCatalogError(f"catalog schema {version} is newer than supported {CATALOG_SCHEMA_VERSION}")
            if version < 1:
                connection.executescript(
                    """BEGIN;
                    CREATE TABLE IF NOT EXISTS skills(
                        id INTEGER PRIMARY KEY, normalized_name TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
                        description TEXT NOT NULL, state TEXT NOT NULL, category TEXT NOT NULL, package_path TEXT NOT NULL,
                        content_hash TEXT NOT NULL UNIQUE, semantic_fingerprint TEXT NOT NULL, vector_json TEXT,
                        embedding_model TEXT, metadata_json TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(name, description, body);
                    CREATE TABLE IF NOT EXISTS skill_sources(id INTEGER PRIMARY KEY, skill_name TEXT NOT NULL, source_type TEXT NOT NULL,
                        source_url TEXT, repository_url TEXT, source_ref TEXT, bundle_hash TEXT, provenance_json TEXT NOT NULL DEFAULT '{}');
                    CREATE TABLE IF NOT EXISTS duplicate_reviews(id INTEGER PRIMARY KEY, left_name TEXT NOT NULL, right_name TEXT NOT NULL,
                        score REAL NOT NULL, status TEXT NOT NULL, decision_reason TEXT, created_at TEXT NOT NULL, decided_at TEXT,
                        UNIQUE(left_name,right_name));
                    CREATE TABLE IF NOT EXISTS pending_references(id TEXT PRIMARY KEY, skill_name TEXT NOT NULL, mutation_id TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS skill_audit(id INTEGER PRIMARY KEY, event TEXT NOT NULL, skill_name TEXT,
                        details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                    PRAGMA user_version=1;
                    COMMIT;"""
                )
                version = 1
            if version < 2:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(skill_audit)")}
                if "event_key" not in columns:
                    connection.execute("ALTER TABLE skill_audit ADD COLUMN event_key TEXT")
                connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS skill_audit_event_key ON skill_audit(event_key) WHERE event_key IS NOT NULL")
                connection.execute("CREATE INDEX IF NOT EXISTS skill_audit_time ON skill_audit(created_at DESC,id DESC)")
                connection.execute("CREATE INDEX IF NOT EXISTS skill_audit_skill_time ON skill_audit(skill_name,created_at DESC)")
                connection.execute("PRAGMA user_version=2")
                connection.commit()
