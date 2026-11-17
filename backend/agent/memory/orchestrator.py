"""Memory orchestration across short-term recall, durable cards, and Honcho.

The orchestrator is the single backend entry point for memory-aware turns:

- store completed user/assistant turns with tool evidence,
- preserve compact tool facts so future related questions can be answered from memory,
- update Honcho conversation memory without blocking chat,
- build context packs that tell the agent whether memory is enough or live tools are needed.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agent.memory.fts5 import FTS5Memory
from agent.memory.provider_extensions import MemoryProviderExtensionManager, build_default_memory_provider_extensions
from agent.memory.resolved import ResolvedQuestionsCache
from agent.memory.specialist_cache import CacheDecision, SpecialistResponseCache
from agent.profiles import AgentProfile
from agent.agents.base import SpecialistResponse
from agent.memory.sessions import SESSIONS_DB
from agent.privacy.classifier import DataClass, classify
from agent.tools.capabilities.memory_service import MemoryCapabilityService


_LIVE_HINTS = {
    "current",
    "currently",
    "latest",
    "live",
    "next",
    "now",
    "today",
    "tomorrow",
    "tonight",
    "upcoming",
    "yesterday",
}

DEFAULT_MEMORY_SETTINGS: dict[str, bool | int] = {
    "memory_enabled": True,
    "dreaming_enabled": True,
    "reference_history_enabled": True,
    "save_new_memories": True,
    "auto_archive_enabled": True,
    # Archived memories stay recallable until they are distilled and deleted.
    "use_archived_memories": True,
    "include_sensitive": False,
    # Retention: inferred memories and history archive after this many days,
    # then are distilled into a digest and permanently deleted.
    "archive_after_days": 30,
    "delete_after_days": 90,
}

# The provider that mirrors durable memories (via the memory_sync ledger).
SYNC_PROVIDER = "hindsight"

# Where a memory came from. Stated memories are things the user said directly;
# they are never removed by retention.
MEMORY_ORIGINS = ("stated", "inferred", "imported", "digest")

_MEMORY_ITEM_COLUMNS = {
    "title": "TEXT NOT NULL DEFAULT ''",
    "description": "TEXT NOT NULL DEFAULT ''",
    "topic": "TEXT NOT NULL DEFAULT ''",
    "origin": "TEXT NOT NULL DEFAULT 'inferred'",
    "last_used_at": "TEXT",
    "use_count": "INTEGER NOT NULL DEFAULT 0",
    "suppressed": "INTEGER NOT NULL DEFAULT 0",
    # Relevance feedback from the "Recalled from memory" chip: +1 relevant, -1 not.
    "feedback_score": "INTEGER NOT NULL DEFAULT 0",
}


class SQLiteMemoryStore:
    """Small orchestration layer over Vellum's existing local SQLite memory DB."""

    def __init__(self, db_path: str | Path = SESSIONS_DB) -> None:
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
                CREATE TABLE IF NOT EXISTS memory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL DEFAULT 'global',
                    kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_thread_id TEXT,
                    confidence REAL NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived_at TEXT
                )
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(memory_items)").fetchall()}
            if "scope" not in columns:
                conn.execute("ALTER TABLE memory_items ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'")
            for column, ddl in _MEMORY_ITEM_COLUMNS.items():
                if column not in columns:
                    conn.execute(f"ALTER TABLE memory_items ADD COLUMN {column} {ddl}")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_sync (
                    memory_id INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (memory_id, provider)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_provider_docs (
                    doc_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (doc_id, provider)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_growth (
                    day TEXT PRIMARY KEY,
                    counts_json TEXT NOT NULL,
                    milestones_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_summaries (
                    scope TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    memory_id INTEGER,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def add_pending(
        self,
        *,
        kind: str,
        text: str,
        source_thread_id: str,
        confidence: float,
        scope: str = "global",
        **meta: Any,
    ) -> int:
        return self._insert_memory(
            scope=scope,
            kind=kind,
            text=text,
            status="pending",
            source_thread_id=source_thread_id,
            confidence=confidence,
            **meta,
        )

    def save_memory(
        self,
        *,
        kind: str,
        text: str,
        source_thread_id: str,
        confidence: float,
        scope: str = "global",
        **meta: Any,
    ) -> int:
        meta.setdefault("origin", "stated")
        memory_id = self._insert_memory(
            scope=scope,
            kind=kind,
            text=text,
            status="saved",
            source_thread_id=source_thread_id,
            confidence=confidence,
            **meta,
        )
        self.audit("saved", memory_id, text)
        self.sync_mark(memory_id, SYNC_PROVIDER, state="pending")
        return memory_id

    def _insert_memory(
        self,
        *,
        scope: str,
        kind: str,
        text: str,
        status: str,
        source_thread_id: str,
        confidence: float,
        title: str = "",
        description: str = "",
        topic: str = "",
        origin: str = "inferred",
    ) -> int:
        now = self._now()
        clean_scope = _normalize_scope(scope)
        if origin not in MEMORY_ORIGINS:
            origin = "inferred"
        title = title or _memory_title(text)
        topic = topic or _memory_topic(kind, text)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memory_items (
                    scope, kind, text, status, source_thread_id, confidence, created_at, updated_at,
                    title, description, topic, origin
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (clean_scope, kind, text, status, source_thread_id, float(confidence), now, now,
                 title, description or text[:200], topic, origin),
            )
            return int(cursor.lastrowid)

    def list_pending(self, *, scopes: list[str] | None = None) -> list[dict[str, Any]]:
        return self._list("pending", scopes=scopes)

    def list_saved(self, *, scopes: list[str] | None = None) -> list[dict[str, Any]]:
        return self._list("saved", scopes=scopes)

    def list_archived(self, *, scopes: list[str] | None = None) -> list[dict[str, Any]]:
        return self._list("archived", scopes=scopes)

    def _list(self, status: str, *, scopes: list[str] | None = None) -> list[dict[str, Any]]:
        clean_scopes = [_normalize_scope(scope) for scope in scopes or []]
        with self._connect() as conn:
            if clean_scopes:
                placeholders = ",".join("?" for _ in clean_scopes)
                rows = conn.execute(
                    f"""
                    SELECT * FROM memory_items
                    WHERE status = ? AND scope IN ({placeholders})
                    ORDER BY pinned DESC, updated_at DESC, id DESC
                    """,
                    (status, *clean_scopes),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM memory_items
                    WHERE status = ?
                    ORDER BY pinned DESC, updated_at DESC, id DESC
                    """,
                    (status,),
                ).fetchall()
        return [_row_dict(row) for row in rows]

    def search_saved(self, query: str, *, limit: int = 8, scopes: list[str] | None = None) -> list[dict[str, Any]]:
        terms = _terms(query)
        rows = self.list_saved(scopes=scopes)
        if terms:
            matched = [row for row in rows if terms.intersection(_terms(row["text"]))]
            if matched:
                rows = matched
        return rows[: max(0, int(limit))]

    def get_memory(self, memory_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_items WHERE id = ?", (int(memory_id),)).fetchone()
        if row is None:
            raise KeyError(memory_id)
        return _row_dict(row)

    def promote(self, memory_id: int) -> dict[str, Any]:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_items
                SET status = 'saved', updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, int(memory_id)),
            )
        item = self.get_memory(memory_id)
        self.audit("promoted", memory_id, item["text"])
        if item["status"] == "saved":
            self.sync_mark(memory_id, SYNC_PROVIDER, state="pending")
        return item

    def archive(self, memory_id: int) -> dict[str, Any]:
        item = self.get_memory(memory_id)
        if item["pinned"]:
            return item
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_items
                SET status = 'archived', archived_at = ?, updated_at = ?
                WHERE id = ? AND pinned = 0
                """,
                (now, now, int(memory_id)),
            )
        archived = self.get_memory(memory_id)
        self.audit("archived", memory_id, archived["text"])
        return archived

    def delete(self, memory_id: int) -> None:
        item = self.get_memory(memory_id)
        if item["pinned"]:
            raise ValueError("Pinned memories cannot be deleted")
        self.purge(memory_id, reason="deleted", kind=item["kind"])

    def purge(self, memory_id: int, *, reason: str = "deleted", kind: str = "") -> None:
        """Permanently remove a memory and every trace of its text in this store.

        Earlier audit rows quoted the memory's text; they are scrubbed so a
        deleted memory is actually forgotten. The new audit row records only
        the id and kind.
        """
        with self._connect() as conn:
            conn.execute("DELETE FROM memory_items WHERE id = ?", (int(memory_id),))
            conn.execute(
                "UPDATE memory_audit_log SET detail = '[removed]' WHERE memory_id = ?",
                (int(memory_id),),
            )
            # A provider copy that was never sent needs nothing; one that was
            # sent must be deleted there too.
            conn.execute(
                "DELETE FROM memory_sync WHERE memory_id = ? AND state IN ('pending', 'failed') AND attempts = 0",
                (int(memory_id),),
            )
            conn.execute(
                "UPDATE memory_sync SET state = 'forget', attempts = 0, last_error = '' WHERE memory_id = ?",
                (int(memory_id),),
            )
        self.audit(reason, memory_id, f"kind={kind}" if kind else "")

    def scrub_deleted_audit_text(self) -> int:
        """One-time cleanup: older builds quoted deleted memories in the audit log."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE memory_audit_log SET detail = '[removed]'
                WHERE memory_id IN (
                    SELECT DISTINCT memory_id FROM memory_audit_log WHERE event IN ('deleted', 'retention_deleted')
                ) AND detail NOT IN ('[removed]', '') AND detail NOT LIKE 'kind=%'
                """
            )
            return max(int(cursor.rowcount), 0)

    def mark_used(self, memory_ids: list[int]) -> None:
        ids = [int(item) for item in memory_ids]
        if not ids:
            return
        now = self._now()
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE memory_items SET use_count = use_count + 1, last_used_at = ? WHERE id IN ({placeholders})",
                (now, *ids),
            )

    def set_suppressed(self, memory_id: int, suppressed: bool = True) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "UPDATE memory_items SET suppressed = ?, updated_at = ? WHERE id = ?",
                (1 if suppressed else 0, self._now(), int(memory_id)),
            )
        self.audit("suppressed" if suppressed else "unsuppressed", memory_id, "")
        return self.get_memory(memory_id)

    def adjust_feedback(self, memory_id: int, delta: int) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "UPDATE memory_items SET feedback_score = MAX(-5, MIN(5, feedback_score + ?)) WHERE id = ?",
                (int(delta), int(memory_id)),
            )
        self.audit("feedback", memory_id, "relevant" if delta > 0 else "not_relevant")
        return self.get_memory(memory_id)

    def set_meta(self, memory_id: int, **fields: Any) -> dict[str, Any]:
        allowed = {key: value for key, value in fields.items() if key in {"title", "description", "topic", "origin"}}
        if allowed:
            assignments = ", ".join(f"{key} = ?" for key in allowed)
            with self._connect() as conn:
                conn.execute(
                    f"UPDATE memory_items SET {assignments}, updated_at = ? WHERE id = ?",
                    (*allowed.values(), self._now(), int(memory_id)),
                )
        return self.get_memory(memory_id)

    # -- provider sync ledger -------------------------------------------------

    def sync_mark(self, memory_id: int, provider: str, *, state: str, doc_id: str = "", error: str = "") -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_sync (memory_id, provider, doc_id, state, attempts, last_error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id, provider) DO UPDATE SET
                    doc_id = CASE WHEN excluded.doc_id != '' THEN excluded.doc_id ELSE memory_sync.doc_id END,
                    state = excluded.state,
                    attempts = CASE
                        WHEN excluded.last_error != '' THEN memory_sync.attempts + 1
                        WHEN excluded.state = 'synced' THEN 0
                        ELSE memory_sync.attempts END,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (int(memory_id), provider, doc_id or f"vellum-memory-{int(memory_id)}", state,
                 1 if error else 0, _squash(error, limit=300), now),
            )

    def sync_pending(self, provider: str, *, max_attempts: int = 5, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_sync
                WHERE provider = ? AND state IN ('pending', 'failed', 'forget') AND attempts < ?
                ORDER BY updated_at ASC LIMIT ?
                """,
                (provider, int(max_attempts), int(limit)),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def record_provider_doc(self, doc_id: str, provider: str, kind: str) -> None:
        if not doc_id:
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO memory_provider_docs (doc_id, provider, kind, created_at) VALUES (?, ?, ?, ?)",
                (doc_id, provider, kind, self._now()),
            )

    def provider_docs_before(self, provider: str, cutoff_iso: str, *, kind: str = "turn") -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT doc_id FROM memory_provider_docs WHERE provider = ? AND kind = ? AND created_at < ?",
                (provider, kind, cutoff_iso),
            ).fetchall()
        return [str(row["doc_id"]) for row in rows]

    def drop_provider_doc(self, doc_id: str, provider: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM memory_provider_docs WHERE doc_id = ? AND provider = ?", (doc_id, provider))

    def sync_drop(self, memory_id: int, provider: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM memory_sync WHERE memory_id = ? AND provider = ?", (int(memory_id), provider))

    def sync_status(self, provider: str) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT state, COUNT(*) AS n FROM memory_sync WHERE provider = ? GROUP BY state", (provider,)
            ).fetchall()
        return {str(row["state"]): int(row["n"]) for row in rows}

    # -- growth snapshots -----------------------------------------------------

    def record_growth(self, day: str, counts: dict[str, Any], milestones: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_growth (day, counts_json, milestones_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET counts_json = excluded.counts_json,
                    milestones_json = excluded.milestones_json
                """,
                (day, json.dumps(counts, sort_keys=True), json.dumps(milestones), self._now()),
            )

    def growth(self, *, limit: int = 90) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_growth ORDER BY day DESC LIMIT ?", (int(limit),)
            ).fetchall()
        out = []
        for row in reversed(rows):
            out.append({
                "day": row["day"],
                "counts": json.loads(row["counts_json"]),
                "milestones": json.loads(row["milestones_json"]),
            })
        return out

    def list_all(self, *, statuses: tuple[str, ...] = ("saved", "archived", "pending")) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM memory_items WHERE status IN ({placeholders}) ORDER BY created_at ASC, id ASC",
                statuses,
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def pin(self, memory_id: int, pinned: bool = True) -> dict[str, Any]:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE memory_items SET pinned = ?, updated_at = ? WHERE id = ?",
                (1 if pinned else 0, now, int(memory_id)),
            )
        item = self.get_memory(memory_id)
        self.audit("pinned" if pinned else "unpinned", memory_id, item["text"])
        return item

    def update(self, memory_id: int, *, text: str | None = None, kind: str | None = None) -> dict[str, Any]:
        item = self.get_memory(memory_id)
        if item["pinned"]:
            raise ValueError("Pinned memories cannot be edited automatically")
        next_text = text if text is not None else item["text"]
        next_kind = kind if kind is not None else item["kind"]
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE memory_items SET text = ?, kind = ?, title = ?, description = ?, updated_at = ? WHERE id = ?",
                (next_text, next_kind, _memory_title(next_text), next_text[:200], now, int(memory_id)),
            )
        updated = self.get_memory(memory_id)
        self.audit("updated", memory_id, updated["text"])
        if updated["status"] == "saved":
            self.sync_mark(memory_id, SYNC_PROVIDER, state="pending")
        return updated

    def global_summary(self) -> str:
        return self.summary("global")

    def update_global_summary(self, summary: str) -> None:
        self.update_summary("global", summary)

    def project_summary(self, project: str | None) -> str:
        if not project:
            return ""
        return self.summary(f"project:{project}")

    def update_project_summary(self, project: str, summary: str) -> None:
        self.update_summary(f"project:{project}", summary)

    def summary(self, scope: str) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT summary FROM memory_summaries WHERE scope = ?", (scope,)).fetchone()
        return str(row["summary"]) if row else ""

    def update_summary(self, scope: str, summary: str) -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_summaries (scope, summary, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(scope) DO UPDATE SET summary = excluded.summary, updated_at = excluded.updated_at
                """,
                (scope, summary, now),
            )

    def audit(self, event: str, memory_id: int | None, detail: str) -> dict[str, Any]:
        now = self._now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memory_audit_log (event, memory_id, detail, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (event, memory_id, _squash(detail, limit=1000), now),
            )
            return {"id": int(cursor.lastrowid), "event": event, "memory_id": memory_id, "detail": detail, "created_at": now}

    def audit_log(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_audit_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(0, int(limit)),),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def get_settings(self) -> dict[str, Any]:
        settings: dict[str, Any] = dict(DEFAULT_MEMORY_SETTINGS)
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM memory_settings").fetchall()
        for row in rows:
            if row["key"] not in settings:
                continue
            settings[row["key"]] = _coerce_setting(row["key"], row["value"])
        return settings

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = set(DEFAULT_MEMORY_SETTINGS)
        now = self._now()
        applied: dict[str, Any] = {}
        with self._connect() as conn:
            for key, value in patch.items():
                if key not in allowed:
                    continue
                clean = _coerce_setting(key, value)
                applied[key] = clean
                conn.execute(
                    """
                    INSERT INTO memory_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (key, json.dumps(clean), now),
                )
        self.audit("settings_updated", None, json.dumps(applied, sort_keys=True))
        return self.get_settings()


@dataclass(slots=True)
class MemoryOrchestrator:
    fts5: FTS5Memory
    resolved_cache: ResolvedQuestionsCache
    memory_service: MemoryCapabilityService
    store: SQLiteMemoryStore | None = None
    honcho: Any | None = None
    memory_dir: Path = Path("data/memory")
    provider_extensions: MemoryProviderExtensionManager | None = None
    specialist_cache: SpecialistResponseCache | None = None
    knowledge_core: Any | None = None

    def __post_init__(self) -> None:
        if self.store is None:
            self.store = SQLiteMemoryStore()
        self.memory_dir = Path(self.memory_dir)
        if self.specialist_cache is None:
            self.specialist_cache = SpecialistResponseCache(self.memory_dir / "specialist-cache.db")
        if self.provider_extensions is None:
            self.provider_extensions = build_default_memory_provider_extensions()

    def save_explicit_memory(
        self,
        *,
        kind: str,
        text: str,
        source_thread_id: str,
        confidence: float,
        scope: str = "global",
        **meta: Any,
    ) -> dict[str, Any]:
        """Persist a user-authored memory and update its canonical search projection."""

        if self.store is None:
            raise RuntimeError("memory store unavailable")
        memory_id = self.store.save_memory(
            kind=kind,
            text=text,
            source_thread_id=source_thread_id,
            confidence=confidence,
            scope=scope,
            **meta,
        )
        self.fts5.add_document(
            content=f"Saved memory: {text}",
            thread_id=source_thread_id,
            source_paths=[f"memory:{memory_id}"],
        )
        return self.store.get_memory(memory_id)

    def flush_provider_sync(self, *, limit: int = 50) -> dict[str, Any]:
        """Send queued memory changes to Hindsight; failures stay queued for retry.

        Every durable memory is mirrored as its own document, so a forget in
        Vellum deletes exactly that document in Hindsight.
        """
        result: dict[str, Any] = {"retained": 0, "forgotten": 0, "failed": 0, "skipped": ""}
        if self.store is None or self.provider_extensions is None:
            result["skipped"] = "no_store"
            return result
        provider = self.provider_extensions.get(SYNC_PROVIDER)
        health = getattr(provider, "health", None)
        if provider is None or not hasattr(provider, "retain_memory") or (callable(health) and not health()):
            result["skipped"] = "provider_unavailable"
            return result
        for row in self.store.sync_pending(SYNC_PROVIDER, limit=limit):
            memory_id = int(row["memory_id"])
            try:
                if row["state"] == "forget":
                    provider.forget_document(str(row["doc_id"]))
                    self.store.sync_drop(memory_id, SYNC_PROVIDER)
                    result["forgotten"] += 1
                    continue
                try:
                    memory = self.store.get_memory(memory_id)
                except KeyError:
                    self.store.sync_drop(memory_id, SYNC_PROVIDER)
                    continue
                if memory["status"] != "saved" or memory.get("suppressed"):
                    self.store.sync_drop(memory_id, SYNC_PROVIDER)
                    continue
                doc_id = provider.retain_memory(memory)
                self.store.sync_mark(memory_id, SYNC_PROVIDER, state="synced", doc_id=doc_id)
                result["retained"] += 1
            except Exception as exc:  # noqa: BLE001 - the ledger keeps the error for retry
                self.store.sync_mark(memory_id, SYNC_PROVIDER, state="failed" if row["state"] != "forget" else "forget",
                                     error=str(exc))
                result["failed"] += 1
        return result

    def lookup_specialist_response(self, *, profile: AgentProfile, query: str) -> CacheDecision:
        if self.store is not None:
            settings = self.store.get_settings()
            if not settings.get("memory_enabled", True) or not settings.get("reference_history_enabled", True):
                return CacheDecision(status="miss", reason="memory_lookup_disabled")
        return self.specialist_cache.lookup(
            profile_id=profile.id,
            profile_version=profile.version,
            query=query,
            policy=profile.cache,
        )

    def store_specialist_response(
        self,
        *,
        profile: AgentProfile,
        query: str,
        response: SpecialistResponse,
    ) -> bool:
        if self.store is not None:
            settings = self.store.get_settings()
            if not settings.get("memory_enabled", True) or not settings.get("save_new_memories", True):
                return False
        return self.specialist_cache.store(
            profile_id=profile.id,
            profile_version=profile.version,
            query=query,
            response=response,
            policy=profile.cache,
        )

    def record_turn(
        self,
        *,
        thread_id: str,
        query: str,
        answer: str,
        tools: list[dict[str, Any]] | None = None,
        sources: list[str] | None = None,
        confidence: float = 0.0,
        agent_name: str = "VellumAgent",
        external_query: str | None = None,
        external_answer: str | None = None,
    ) -> dict[str, Any]:
        clean_query = query.strip()
        clean_answer = answer.strip()
        provider_query = clean_query if external_query is None else external_query.strip()
        provider_answer = clean_answer if external_answer is None else external_answer.strip()
        compact_tools = [_compact_tool(tool) for tool in tools or []]
        source_list = [str(source) for source in sources or [] if str(source).strip()]
        content = _turn_document(
            query=clean_query,
            answer=clean_answer,
            tools=compact_tools,
            sources=source_list,
            agent_name=agent_name,
        )
        rowid = self.fts5.add_document(content=content, thread_id=thread_id, source_paths=source_list)

        resolved_cached = False
        if confidence >= 0.85:
            self.resolved_cache.store(
                query=clean_query,
                answer_summary=clean_answer,
                sources=source_list,
                confidence=confidence,
                model=agent_name,
            )
            resolved_cached = True

        # Obsidian cards are projections of reviewed SQLite memories. A raw
        # high-confidence turn must not create a second durable authority.
        memory_card_path = ""

        if self.honcho is not None:
            session_id = self.honcho.get_or_create_session(thread_id)
            self.honcho.add_message(session_id, content=provider_query, role="user")
            self.honcho.add_message(session_id, content=provider_answer, role="assistant")

        external_sync = []
        if self.provider_extensions is not None:
            external_sync = self.provider_extensions.sync_turn(
                provider_query,
                provider_answer,
                session_id=thread_id,
                metadata={
                    "agent_name": agent_name,
                    "tools": compact_tools,
                    "sources": source_list,
                    "confidence": confidence,
                },
            )
            if self.store is not None:
                # Turn documents are history: the retention job deletes them
                # from the provider once they pass delete_after_days.
                for synced in external_sync:
                    self.store.record_provider_doc(str(synced.get("doc_id") or ""), str(synced.get("provider")), "turn")

        knowledge_core_result: dict[str, Any] = {"stored": False, "reason": "knowledge_core_unavailable"}
        if self.knowledge_core is not None:
            try:
                knowledge_core_result = self.knowledge_core.record_turn(
                    thread_id=thread_id,
                    query=clean_query,
                    answer=clean_answer,
                    tools=compact_tools,
                    sources=source_list,
                    agent_name=agent_name,
                )
            except Exception as exc:
                # Shadow ingestion cannot make the existing memory write fail.
                knowledge_core_result = {"stored": False, "reason": "shadow_write_failed", "error": str(exc)[:300]}

        return {
            "stored": True,
            "fts5_id": rowid,
            "resolved_cached": resolved_cached,
            "memory_card_path": memory_card_path,
            "external_sync": external_sync,
            "knowledge_core": knowledge_core_result,
        }

    def build_memory_packet(
        self,
        *,
        thread_id: str,
        query: str,
        agent_name: str = "VellumAgent",
        active_project: str | None = None,
        cloud_safe: bool = False,
        read_scopes: list[str] | None = None,
        live_honcho: bool = True,
        include_history: bool = True,
        include_external: bool = True,
        select_with_model: bool = False,
    ) -> dict[str, Any]:
        clean_query = query.strip()
        scopes = list(dict.fromkeys(read_scopes)) if read_scopes is not None else _packet_scopes(
            agent_name=agent_name,
            active_project=active_project,
        )
        settings = self.store.get_settings() if self.store is not None else dict(DEFAULT_MEMORY_SETTINGS)
        if not settings.get("memory_enabled", True):
            return {
                "global_summary": "",
                "saved_memories": [],
                "honcho_context": "",
                "project_context": "",
                "recent_context": "",
                "scopes": scopes,
                "settings": settings,
            }
        saved: list[dict[str, Any]] = []
        recall_method = "none"
        if self.store is not None:
            baseline_scopes = [scope for scope in scopes if scope in {"global", "user_profile"} or scope.startswith("project:")]
            if agent_name == 'MusicAgent' and 'agent:MusicAgent' in scopes:
                # Vague suggestions still need this agent's approved preferences.
                # Keep the existing scope policy; do not read global history.
                baseline_scopes.append('agent:MusicAgent')
            if select_with_model:
                saved, recall_method = self._select_for_prompt(clean_query, scopes, baseline_scopes, settings)
            else:
                baseline = _durable_memories(self.store.list_saved(scopes=baseline_scopes))[:4] if baseline_scopes else []
                matched = _durable_memories(self.store.search_saved(clean_query, limit=12, scopes=scopes))
                saved = _dedupe_memories([*baseline, *matched])[:8]
                recall_method = "keyword"
        strict_profile_scope = read_scopes is not None
        docs = (
            self.fts5.search(_memory_search_query(clean_query), limit=5)
            if include_history and settings.get("reference_history_enabled", True) and not strict_profile_scope
            else []
        )
        honcho_context = ""
        if live_honcho and self.honcho is not None and (not strict_profile_scope or "user_profile" in scopes):
            try:
                honcho_context = str(self.honcho.chat(session_id=thread_id, query=clean_query) or "")
            except Exception:
                honcho_context = ""
        docs = docs or (
            self.fts5.recent_documents(limit=5)
            if include_history and settings.get("reference_history_enabled", True) and not strict_profile_scope
            else []
        )
        external_context = (
            self.provider_extensions.prefetch(clean_query, session_id=thread_id)
            if self.provider_extensions and include_external and not strict_profile_scope
            else []
        )
        packet = {
            "global_summary": (
                _safe_global_summary(self.store)
                if self.store is not None and (not strict_profile_scope or "global" in scopes)
                else ""
            ),
            "saved_memories": saved,
            "honcho_context": honcho_context,
            "project_context": (
                self.store.project_summary(active_project)
                if self.store is not None and active_project and (not strict_profile_scope or f"project:{_normalize_scope(active_project)}" in scopes)
                else ""
            ),
            "recent_context": "\n\n".join(str(doc.get("content") or "") for doc in docs[:3]),
            "external_context": "\n\n".join(item["context"] for item in external_context if item.get("context")),
            "external_providers": external_context,
            "recall_method": recall_method if self.store is not None else "none",
            "scopes": scopes,
            "settings": settings,
        }
        if cloud_safe:
            packet = _scrub_packet(packet)
        return packet

    def _select_for_prompt(self, query: str, scopes: list[str], baseline_scopes: list[str],
                           settings: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        """Standing rules always apply; a small model picks up to 5 more.

        Pinned memories, preferences and corrections act like an always-loaded
        index. Everything else competes for the remaining slots by relevance.
        Archived memories stay recallable while ``use_archived_memories`` is on.
        """
        from agent.memory.recall import select_relevant_memories

        assert self.store is not None
        standing = [
            item for item in _durable_memories(self.store.list_saved(scopes=baseline_scopes))
            if item.get("pinned") or item.get("kind") in {"preference", "correction"}
        ][:6] if baseline_scopes else []
        standing_ids = {item["id"] for item in standing}
        pool = _durable_memories(self.store.list_saved(scopes=scopes))
        if settings.get("use_archived_memories", True):
            pool += _durable_memories(self.store.list_archived(scopes=scopes))
        pool = [item for item in pool if item["id"] not in standing_ids]
        chosen, method = select_relevant_memories(query, pool, limit=5)
        selected = _dedupe_memories([*standing, *chosen])[:10]
        if not method.startswith("cached"):
            self.store.mark_used([item["id"] for item in chosen])
        return selected, method

    def build_agent_handoff(self, *, source, recipient, query: str, thread_id: str,
                           user_id: str, recent: dict | None = None) -> dict[str, Any]:
        """Resolve relevant evidence under both profiles' policies; never copy history."""
        from datetime import UTC, datetime, timedelta
        from agent.memory.packets import AgentMemoryPacket, PacketEvidence
        from agent.privacy.scrubber import PrivacyScrubber
        def contains_secret(text):
            return any(pattern.search(text) for label, pattern, _ in PrivacyScrubber.regex_patterns
                       if label in {"SECRET", "CRYPTO_KEY", "CREDIT_CARD", "GOVERNMENT_ID"}) or bool(
                       re.search(r"auth_token|\bct0\b|\bbearer\s+\S+|-----BEGIN", text, re.I))
        if source.id != recipient.id and (
            recipient.id not in source.memory.share_with or source.id not in recipient.memory.receive_from
            or recipient.source_egress != "local"
        ):
            raise PermissionError("This memory handoff is not allowed by both profiles")
        now = datetime.now(UTC)
        items = []
        if self.store is not None and self.store.get_settings().get("memory_enabled", True):
            authorized_scopes = source.memory.read_scopes if source.id == recipient.id else source.memory.share_scopes
            scopes = [scope for scope in source.memory.read_scopes
                      if scope in {"shared", f"agent:{source.id}"} and scope in authorized_scopes]
            matches = self.store.search_saved(query, limit=4, scopes=scopes) if scopes else []
            for item in matches:
                if contains_secret(str(item["text"])):
                    continue
                items.append(PacketEvidence(reference=f"memory:{item['id']}", scope=item["scope"],
                    text=str(item["text"])[:1600], confidence=float(item.get("confidence") or 0),
                    updated_at=str(item.get("updated_at") or "")))
            recent = recent or {}
            captured = recent.get("captured_at", "")
            try:
                age = (now - datetime.fromisoformat(captured)).total_seconds()
            except (ValueError, TypeError):
                age = -1
            tokens = lambda text: set(re.findall(r"[a-z0-9]{3,}", str(text).casefold())) - {"what","about","this","that","have","with","from","please","tell","know","does","your","their"}
            if (recent.get("user_id") == user_id and 0 <= age <= 600
                    and source.result_visibility == "full"
                    and f"agent:{source.id}" in scopes
                    and not contains_secret(json.dumps(recent, default=str))
                    and tokens(query) & tokens(recent.get("purpose", ""))):
                items.append(PacketEvidence(reference=str(recent["reference"]), scope=f"agent:{source.id}",
                    text=str(recent.get("summary") or "")[:1600], confidence=float(recent.get("confidence") or 0),
                    updated_at=captured, sources=[str(s)[:500] for s in recent.get("sources", [])[:6]]))
        return AgentMemoryPacket(source_agent=source.id, recipient_agent=recipient.id, purpose=query[:1000],
            thread_id=thread_id, user_id=user_id, captured_at=now, expires_at=now+timedelta(minutes=5),
            items=items).model_dump(mode="json")

    def topics_view(self) -> list[dict[str, Any]]:
        """Saved and archived memories grouped into topic cards, newest learning first."""
        if self.store is None:
            return []
        groups: dict[str, dict[str, Any]] = {}
        for item in self.store.list_saved() + self.store.list_archived():
            if not _is_durable_memory_text(str(item.get("text") or "")):
                continue
            topic = item.get("topic") or _memory_topic(str(item.get("kind") or ""), str(item.get("text") or ""))
            card = groups.setdefault(topic, {"topic": topic, "count": 0, "last_learned": "",
                                             "origins": {}, "items": []})
            card["count"] += 1
            card["last_learned"] = max(card["last_learned"], str(item.get("created_at") or ""))
            origin = str(item.get("origin") or "inferred")
            card["origins"][origin] = card["origins"].get(origin, 0) + 1
            card["items"].append({key: item.get(key) for key in (
                "id", "title", "text", "kind", "origin", "status", "pinned", "suppressed",
                "use_count", "last_used_at", "created_at", "updated_at")})
        for card in groups.values():
            card["items"].sort(key=lambda entry: str(entry.get("created_at") or ""), reverse=True)
        return sorted(groups.values(), key=lambda card: card["last_learned"], reverse=True)

    def summary_view(self) -> dict[str, Any]:
        """Return one stable, UI-ready memory contract for every frontend surface."""
        if self.store is None:
            return {
                "global_summary": "",
                "sections": [],
                "saved_memories": [],
                "archived_memories": [],
                "pending_count": 0,
                "audit_log": [],
            }
        saved = _durable_memories(self.store.list_saved())
        archived = self.store.list_archived()
        return {
            "global_summary": _safe_global_summary(self.store),
            "sections": _memory_summary_sections(saved),
            "saved_memories": saved,
            "archived_memories": archived,
            "pending_count": len(_durable_memories(self.store.list_pending())),
            "audit_log": self.store.audit_log(limit=25),
        }

    def build_context_pack(self, *, thread_id: str, query: str, agent_name: str = "VellumAgent") -> dict[str, Any]:
        clean_query = query.strip()
        resolved = self.resolved_cache.get(clean_query) or self.resolved_cache.find_related(clean_query)
        docs = self.fts5.search(_memory_search_query(clean_query), limit=5)
        cards = self.memory_service.build_context_pack(
            {"query": clean_query, "thread_id": thread_id, "agent_name": agent_name}
        ).get("cards", [])

        sections: list[str] = []
        if resolved:
            sections.append("## Resolved answer\n" + str(resolved.get("answer_summary") or ""))
        if docs:
            sections.append("## Related past turns\n" + "\n\n".join(str(doc.get("content") or "") for doc in docs[:3]))
        if cards:
            sections.append("## Durable memory cards\n" + "\n\n".join(str(card.get("text") or "") for card in cards[:3]))

        has_memory_answer = bool(resolved or docs or cards)
        needs_live = _needs_live_tools(clean_query)
        should_answer_from_memory = has_memory_answer and not (needs_live and not docs and not resolved)
        return {
            "action": "memory.orchestrator.build_context_pack",
            "thread_id": thread_id,
            "agent_name": agent_name,
            "query": clean_query,
            "context": "\n\n".join(sections).strip(),
            "resolved": resolved,
            "documents": docs,
            "cards": cards,
            "should_answer_from_memory": should_answer_from_memory,
            "recommended_live_tools": [] if should_answer_from_memory else ["web_search"],
        }

    def extract_memory_candidates(
        self,
        *,
        thread_id: str,
        user_message: str,
        assistant_message: str = "",
        agent_name: str = "VellumAgent",
    ) -> list[dict[str, Any]]:
        if self.store is None:
            return []
        settings = self.store.get_settings()
        if not settings.get("memory_enabled", True) or not settings.get("save_new_memories", True):
            return []
        candidates = _extract_candidates(user_message, assistant_message)
        main_agent = _scope_for_candidate(agent_name) == "global"
        saved_keys = {_norm(str(item.get("text") or "")) for item in self.store.list_saved()} if main_agent else set()
        stored: list[dict[str, Any]] = []
        for candidate in candidates:
            data_class, _reason = classify(candidate["text"])
            if data_class == DataClass.RED and not _explicit_remember(user_message):
                continue
            # Preferences and corrections describe the user, not one project, so
            # they go to user_profile, which every specialist already reads.
            user_level = main_agent and candidate["kind"] in {"preference", "correction"}
            stated = candidate["confidence"] >= 0.8
            memory_id = self.store.add_pending(
                kind=candidate["kind"],
                text=candidate["text"],
                source_thread_id=thread_id,
                confidence=candidate["confidence"],
                scope="user_profile" if user_level else _scope_for_candidate(agent_name),
                origin="stated" if stated else "inferred",
            )
            self.store.audit("pending_created", memory_id, f"{agent_name}: {candidate['text']}")
            # Things the user stated directly must shape the very next answer,
            # not wait for Dreaming's batch threshold or the 2 a.m. run.
            key = _norm(candidate["text"])
            if main_agent and candidate["confidence"] >= 0.8 and key not in saved_keys:
                self.store.promote(memory_id)
                self.store.audit("auto_promoted", memory_id, "User-stated; applied immediately")
                saved_keys.add(key)
            stored.append(self.store.get_memory(memory_id))
        return stored

    def run_dreaming(self, *, stale_days: int = 30) -> dict[str, Any]:
        if self.store is None:
            return _empty_dream()
        new_memories: list[dict[str, Any]] = []
        updated_memories: list[dict[str, Any]] = []
        archived_memories: list[dict[str, Any]] = []
        contradictions: list[dict[str, Any]] = []

        # Old builds could promote raw UI wrappers, operational commands, and
        # greetings. Preserve their audit trail by archiving them, never deleting.
        for item in [*self.store.list_pending(), *self.store.list_saved()]:
            if item["pinned"] or _is_durable_memory_text(str(item.get("text") or "")):
                continue
            archived_memories.append(self.store.archive(item["id"]))
            self.store.audit("noise_archived", item["id"], "Excluded from durable memory during Dreaming")

        seen_texts = {_norm(item["text"]) for item in _durable_memories(self.store.list_saved())}
        for pending in _durable_memories(self.store.list_pending()):
            key = _norm(pending["text"])
            if key in seen_texts:
                archived_memories.append(self.store.archive(pending["id"]))
                continue
            promoted = self.store.promote(pending["id"])
            new_memories.append(promoted)
            seen_texts.add(key)

        saved = _durable_memories(self.store.list_saved())
        for left_index, left in enumerate(saved):
            for right in saved[left_index + 1 :]:
                if _simple_contradiction(left["text"], right["text"]):
                    contradictions.append({"left": left, "right": right})

        # Age-based archiving lives in the retention job (agent.memory.retention),
        # which keeps stated memories, corrections and pins. stale_days is kept
        # for callers but no longer archives anything here.
        del stale_days

        global_summary = _safe_global_summary(self.store, use_stored_fallback=False)
        self.store.update_global_summary(global_summary)
        context_files = self.sync_context_files()
        audit_log = self.store.audit_log(limit=50)
        return {
            "new_memories": new_memories,
            "updated_memories": updated_memories,
            "archived_memories": archived_memories,
            "contradictions": contradictions,
            "global_summary": global_summary,
            "project_summaries": _project_summaries(self.store.list_saved()),
            "context_files": context_files,
            "audit_log": audit_log,
        }

    def sync_context_files(self) -> dict[str, str]:
        """Write Hermes-style bounded context files from the orchestrator state."""
        if self.store is None:
            return {"user_path": "", "memory_path": ""}
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        saved = self.store.list_saved()
        user_text = _render_user_md(saved, self.store.summary("user_profile"))
        memory_text = _render_memory_md(
            saved,
            global_summary=self.store.global_summary(),
            project_summaries=_project_summaries(saved),
        )
        user_path = self.memory_dir / "USER.md"
        memory_path = self.memory_dir / "MEMORY.md"
        user_path.write_text(user_text, encoding="utf-8")
        memory_path.write_text(memory_text, encoding="utf-8")
        self.store.audit("context_files_synced", None, f"{user_path}; {memory_path}")
        return {"user_path": str(user_path), "memory_path": str(memory_path)}



def _turn_document(
    *,
    query: str,
    answer: str,
    tools: list[dict[str, str]],
    sources: list[str],
    agent_name: str,
) -> str:
    tool_lines = []
    for tool in tools:
        tool_lines.append(f"- {tool['name']}: {tool['facts']}")
    source_lines = [f"- {source}" for source in sources]
    return "\n".join(
        [
            f"Agent: {agent_name}",
            f"Q: {query}",
            f"A: {answer}",
            "Tools:",
            *(tool_lines or ["- none"]),
            "Sources:",
            *(source_lines or ["- none"]),
        ]
    )


def _compact_tool(tool: dict[str, Any]) -> dict[str, str]:
    name = str(tool.get("name") or tool.get("tool") or "tool")
    output = tool.get("output")
    facts = ""
    if isinstance(output, dict):
        facts = (
            str(output.get("reconstructed_markdown") or "")
            or str(output.get("answer") or "")
            or str(output.get("snippet") or "")
            or json.dumps(output, ensure_ascii=False, sort_keys=True)
        )
    else:
        facts = str(output or "")
    return {"name": name, "facts": _squash(facts, limit=1200)}


def _evidence_text(tools: list[dict[str, str]], sources: list[str]) -> str:
    parts = []
    if tools:
        parts.append("Tools:\n" + "\n".join(f"- {tool['name']}: {tool['facts']}" for tool in tools))
    if sources:
        parts.append("Sources:\n" + "\n".join(f"- {source}" for source in sources))
    return "\n\n".join(parts).strip()


def _memory_search_query(query: str) -> str:
    terms = []
    for term in re.findall(r"[A-Za-z0-9]+", query.casefold()):
        if len(term) <= 2 or term in {"the", "and", "for", "what", "when", "where", "did", "does", "how", "many"}:
            continue
        terms.append(term)
    unique = list(dict.fromkeys(terms))[:8]
    return " OR ".join(unique) if unique else query


def _needs_live_tools(query: str) -> bool:
    terms = set(re.findall(r"[A-Za-z0-9]+", query.casefold()))
    return bool(terms.intersection(_LIVE_HINTS))


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    if "pinned" in data:
        data["pinned"] = bool(data["pinned"])
    return data


def _terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[A-Za-z0-9]+", text.casefold()) if len(term) > 2}


def _extract_candidates(user_message: str, assistant_message: str) -> list[dict[str, Any]]:
    text = _clean_candidate_text(user_message)
    if not text:
        return []
    candidates: list[dict[str, Any]] = []
    explicit = re.search(
        r"(?:^|[.!?]\s+)(?:please\s+)?(?:remember|memorize|note|keep in mind)\b(?:\s+that)?\s+(?P<fact>.+)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if explicit:
        fact = _clean_candidate_text(explicit.group("fact"))
        if _is_durable_memory_text(fact, explicit=True):
            candidates.append({"kind": _candidate_kind(fact), "text": _sentence(fact), "confidence": 0.92})
    if not _is_durable_memory_text(text):
        return _dedupe_candidates(candidates)
    if re.search(r"\b(?:i prefer|i like|i don't like|i do not like|stop adding|don't include|do not include)\b", text, re.I):
        candidates.append({"kind": "preference", "text": _sentence(text), "confidence": 0.82})
    candidates.extend(_lesson_candidates(text))
    if re.search(r"\b(?:vellum|project|we decided|decision|architecture|backend|frontend)\b", text, re.I):
        candidates.append({"kind": "project", "text": _sentence(text), "confidence": 0.7})
    return _dedupe_candidates(candidates)


# A user telling Vellum it was wrong ("you got that wrong again").
_CORRECTION_MARKER_RE = re.compile(
    r"\b(?:you (?:got|did|made) (?:that|it|this)\s*(?:\w+\s+)?wrong|"
    r"(?:that'?s|that is|this is|it'?s|it is) (?:wrong|incorrect|not (?:right|correct|what i (?:asked|wanted|meant)))|"
    r"you (?:forgot|missed|ignored|didn'?t (?:check|verify|read|listen))|"
    r"i (?:already )?told you|not again|wrong again)\b",
    re.IGNORECASE,
)
# A standing rule for future behavior ("whenever X, do Y", "from now on ...").
_STANDING_RULE_RE = re.compile(
    r"^(?:please\s+)?(?:always|never(?!\s+mind)|whenever|from now on|going forward|in (?:the )?future|next time|"
    r"don'?t ever|do not ever|each time|every time|make sure (?:you|to) always)\b",
    re.IGNORECASE,
)
_IMPERATIVE_RE = re.compile(
    r"^(?:please\s+)?(?:check|verify|confirm|make sure|ensure|use|don'?t|do not|avoid|try|inspect|"
    r"read|look|ask|stop|keep|remember|double-check|test|run|wait|start|prefer)\b",
    re.IGNORECASE,
)


def _lesson_candidates(text: str) -> list[dict[str, Any]]:
    """Standing rules and the lesson inside a correction, as durable candidates.

    "You got that wrong again. Check whether a tool actually succeeded before
    saying it is done." yields the second sentence as a correction; the bare
    complaint alone carries no lesson and yields nothing.
    """
    sentences = [part.strip() for part in re.split(r"(?<=[.!])\s+", text) if part.strip()]
    corrected = bool(_CORRECTION_MARKER_RE.search(text))
    out: list[dict[str, Any]] = []
    for sentence in sentences:
        if sentence.endswith("?") or _CORRECTION_MARKER_RE.fullmatch(sentence.rstrip(".! ")):
            continue
        if len(re.findall(r"[A-Za-z0-9']+", sentence)) < 4 or not _is_durable_memory_text(sentence):
            continue
        if _STANDING_RULE_RE.match(sentence):
            out.append({"kind": "correction" if corrected else "preference", "text": _sentence(sentence), "confidence": 0.85})
        elif corrected and _IMPERATIVE_RE.match(sentence) and not _CORRECTION_MARKER_RE.search(sentence):
            out.append({"kind": "correction", "text": _sentence(sentence), "confidence": 0.85})
    return out


_MEMORY_NOISE_RE = re.compile(
    r"(?:\[vellum ui context:|recency_hunger|stochastic_kick|curiosity[_ -]score|"
    r"\bplease use\b.{0,60}\bagent\b|\banswer (?:this|the)\b.{0,30}\bquestion\b|"
    r"\bdo not include any personal context\b|"
    r"\b(?:for this chat only|demonstration project|reply with (?:its|the) label)\b|"
    r"\b(?:install|download|archive|delete|remove|uninstall|list|show)\b.{0,40}\bskills?\b|"
    r"\bskills?\b.{0,40}\b(?:install|download|archive|delete|remove|uninstall)\b|"
    r"\b(?:tool_call|system prompt|developer message|use the following instructions)\b)",
    re.IGNORECASE | re.DOTALL,
)
_GREETING_RE = re.compile(r"^(?:hi|hey|hello|sup|yo|thanks|thank you|good job|great job)[.!\s]*$", re.IGNORECASE)
_QUESTION_START_RE = re.compile(
    r"^(?:(?:so\s+)?(?:tell me|explain|give|summari[sz]e)|what|when|where|why|who|which|how|can|could|would|should|do|does|did|is|are|was|were|have|has)\b",
    re.IGNORECASE,
)


def _clean_candidate_text(text: str) -> str:
    clean = re.sub(r"\[Vellum UI context:.*?\]", " ", str(text or ""), flags=re.IGNORECASE | re.DOTALL)
    return " ".join(clean.split()).strip()


def _is_durable_memory_text(text: str, *, explicit: bool = False) -> bool:
    clean = _clean_candidate_text(text)
    if len(clean) < 12 or _GREETING_RE.fullmatch(clean) or _MEMORY_NOISE_RE.search(clean):
        return False
    if not explicit and (clean.endswith("?") or _QUESTION_START_RE.match(clean)):
        return False
    if not explicit and re.match(r"^(?:please\s+)?(?:post|publish|tweet|reply|repost|retweet|unrepost|unretweet|like|unlike|bookmark|unbookmark)\b", clean, re.I):
        return False
    if len(re.findall(r"[A-Za-z0-9]+", clean)) < 3:
        return False
    return True


def _durable_memories(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item for item in memories
        if not item.get("suppressed") and _is_durable_memory_text(str(item.get("text") or ""))
    ]


def _safe_global_summary(store: SQLiteMemoryStore, *, use_stored_fallback: bool = True) -> str:
    stored = store.global_summary().strip()
    if use_stored_fallback and stored and not _MEMORY_NOISE_RE.search(stored):
        return stored
    shared = _durable_memories(store.list_saved(scopes=["global", "user_profile", "shared"]))
    if shared:
        return _summarize_memories(shared)
    return ""


def _memory_summary_sections(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = {
        "preference": ("preferences", "Preferences"),
        "project": ("projects", "Projects and decisions"),
        "correction": ("corrections", "Corrections"),
        "goal": ("goals", "Goals"),
        "fact": ("facts", "About you"),
    }
    grouped: dict[str, dict[str, Any]] = {}
    for item in memories:
        section_id, title = labels.get(str(item.get("kind") or "fact"), ("other", "Other memories"))
        section = grouped.setdefault(section_id, {"id": section_id, "title": title, "items": []})
        section["items"].append(item)
    order = ["facts", "preferences", "goals", "projects", "corrections", "other"]
    return [grouped[key] for key in order if key in grouped]


def _candidate_kind(text: str) -> str:
    if re.search(r"\b(?:prefer|like|don't like|do not like|style|tone)\b", text, re.I):
        return "preference"
    if re.search(r"\b(?:vellum|project|architecture|backend|frontend|agent)\b", text, re.I):
        return "project"
    return "fact"


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = _norm(candidate["text"])
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _dedupe_memories(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[int | str] = set()
    for memory in memories:
        key: int | str = int(memory["id"]) if str(memory.get("id", "")).isdigit() else _norm(str(memory.get("text") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(memory)
    return out


def _explicit_remember(text: str) -> bool:
    return bool(re.search(r"(?:^|[.!?]\s+)(?:please\s+)?(?:remember|memorize|note|keep in mind)\b", text, re.I))


def _coerce_setting(key: str, value: Any) -> Any:
    default = DEFAULT_MEMORY_SETTINGS.get(key)
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = raw.strip().lower() == "true" if isinstance(default, bool) else raw
    if isinstance(default, bool):
        return bool(raw)
    if isinstance(default, int):
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return default
    return raw


def _memory_title(text: str) -> str:
    """A short label for the memory, used as its recall key and card title."""
    clean = re.sub(r"\s+", " ", str(text or "")).strip().rstrip(".!")
    clean = re.sub(r"^(?:please\s+)?(?:remember|note|keep in mind)(?:\s+that)?\s+", "", clean, flags=re.I)
    clean = re.sub(r"^i\s+", "", clean, flags=re.I)
    words = clean.split()
    title = " ".join(words[:9])
    if len(words) > 9:
        title += "…"
    return title[:1].upper() + title[1:] if title else ""


_TOPIC_RULES: tuple[tuple[str, str], ...] = (
    (r"\b(?:code|coding|python|typescript|javascript|rust|repo|git|test|api|backend|frontend|bug)\b", "Coding and tools"),
    (r"\b(?:music|song|album|artist|spotify|playlist)\b", "Music"),
    (r"\b(?:book|books|read|reading|author|novel)\b", "Books and reading"),
    (r"\b(?:sport|football|cricket|nba|match|team|league)\b", "Sports"),
    (r"\b(?:youtube|video|creator|channel)\b", "Videos and creators"),
    (r"\b(?:calendar|meeting|schedule|morning|routine|weekday)\b", "Schedule and routines"),
    (r"\b(?:tone|concise|format|bullet|answer|answers|reply|replies|explain|style)\b", "How to talk to me"),
)


def _memory_topic(kind: str, text: str) -> str:
    if kind == "correction":
        return "Lessons and corrections"
    if kind == "digest":
        return "Earlier memories"
    lowered = str(text or "").casefold()
    if kind == "project" or "vellum" in lowered:
        if "vellum" in lowered:
            return "Vellum"
    for pattern, topic in _TOPIC_RULES:
        if re.search(pattern, lowered):
            return topic
    if kind == "project":
        return "Projects"
    if kind == "preference":
        return "Preferences"
    return "About you"


def _sentence(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return ""
    return clean if clean.endswith((".", "!", "?")) else clean + "."


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[A-Za-z0-9]+", text.casefold()))


def _simple_contradiction(left: str, right: str) -> bool:
    left_norm = _norm(left)
    right_norm = _norm(right)
    if not left_norm or not right_norm:
        return False
    pairs = (("like", "dislike"), ("want", "do not want"), ("prefer", "do not prefer"))
    for positive, negative in pairs:
        if positive in left_norm and negative in right_norm:
            return bool(_terms(left_norm).intersection(_terms(right_norm)))
        if negative in left_norm and positive in right_norm:
            return bool(_terms(left_norm).intersection(_terms(right_norm)))
    return False


def _summarize_memories(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return ""
    grouped: dict[str, list[str]] = {}
    for item in memories:
        grouped.setdefault(str(item["kind"]), []).append(str(item["text"]))
    lines: list[str] = []
    for kind in sorted(grouped):
        for text in grouped[kind][:6]:
            lines.append(f"- {kind}: {text}")
    return "\n".join(lines)


def _project_summaries(memories: list[dict[str, Any]]) -> dict[str, str]:
    project_items = [item for item in memories if item["kind"] == "project"]
    if not project_items:
        return {}
    return {"Vellum": "\n".join(f"- {item['text']}" for item in project_items[:8])}


def _render_user_md(memories: list[dict[str, Any]], profile_summary: str = "") -> str:
    lines = [
        "# User Profile",
        "",
        "Curated by Vellum Memory Orchestrator. Edit carefully; Dreaming may sync generated content.",
        "",
    ]
    if profile_summary.strip():
        lines.extend(["## Summary", profile_summary.strip(), ""])
    user_items = [
        item
        for item in memories
        if item.get("scope") == "user_profile" or str(item.get("kind") or "") in {"profile", "preference"}
    ]
    if user_items:
        lines.append("## Entries")
        for item in user_items:
            lines.append(f"- {str(item.get('text') or '').strip()}")
    return _bounded_markdown(lines, limit=1375)


def _render_memory_md(
    memories: list[dict[str, Any]],
    *,
    global_summary: str = "",
    project_summaries: dict[str, str] | None = None,
) -> str:
    lines = [
        "# Agent Memory",
        "",
        "Curated by Vellum Memory Orchestrator from saved memories, tool-backed answers, and Dreaming.",
        "",
    ]
    if global_summary.strip():
        lines.extend(["## Global Summary", global_summary.strip(), ""])
    project_summaries = project_summaries or {}
    if project_summaries:
        lines.append("## Projects")
        for project, summary in sorted(project_summaries.items()):
            lines.append(f"### {project}")
            lines.append(summary.strip())
        lines.append("")
    agent_items = [
        item
        for item in memories
        if item.get("scope") != "user_profile" and str(item.get("kind") or "") not in {"profile", "preference"}
    ]
    if agent_items:
        lines.append("## Entries")
        for item in agent_items:
            scope = str(item.get("scope") or "global")
            text = str(item.get("text") or "").strip()
            lines.append(f"- [{scope}] {text}")
    return _bounded_markdown(lines, limit=2200)


def _bounded_markdown(lines: list[str], *, limit: int) -> str:
    out = ""
    for line in lines:
        next_out = f"{out}\n{line}" if out else line
        if len(next_out) > limit:
            break
        out = next_out
    return out[:limit].rstrip() + "\n"


def _scrub_packet(packet: dict[str, Any]) -> dict[str, Any]:
    from agent.privacy.scrubber import PrivacyScrubber

    scrubber = PrivacyScrubber()
    scrubbed = dict(packet)
    for key in ("global_summary", "honcho_context", "project_context", "recent_context"):
        scrubbed[key] = scrubber.scrub(str(scrubbed.get(key) or ""))[0]
    memories = []
    for item in scrubbed.get("saved_memories", []):
        next_item = dict(item)
        next_item["text"] = scrubber.scrub(str(next_item.get("text") or ""))[0]
        memories.append(next_item)
    scrubbed["saved_memories"] = memories
    return scrubbed


def _empty_dream() -> dict[str, Any]:
    return {
        "new_memories": [],
        "updated_memories": [],
        "archived_memories": [],
        "contradictions": [],
        "global_summary": "",
        "project_summaries": {},
        "audit_log": [],
    }


def _normalize_scope(scope: str | None) -> str:
    clean = re.sub(r"\s+", "_", str(scope or "global").strip())
    return clean or "global"


def _agent_scope(agent_name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]+", "", str(agent_name or "").strip()) or "VellumAgent"
    return f"agent:{clean}"


def _packet_scopes(*, agent_name: str, active_project: str | None = None) -> list[str]:
    scopes = ["global", "user_profile", "shared"]
    if active_project:
        scopes.append(f"project:{_normalize_scope(active_project)}")
    scopes.append(_agent_scope(agent_name))
    return list(dict.fromkeys(scopes))


def _scope_for_agent(agent_name: str) -> str:
    return _agent_scope(agent_name)


def _scope_for_candidate(agent_name: str) -> str:
    normalized_agent = _normalize_scope(agent_name).casefold()
    if normalized_agent in {"vellum", "vellumagent", "main", "mainagent"}:
        return "global"
    return _agent_scope(agent_name)


def _card_title(query: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", query)
    return " ".join(words[:10]) or "Resolved turn"


def _squash(text: str, *, limit: int) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"
