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

DEFAULT_MEMORY_SETTINGS = {
    "memory_enabled": True,
    "dreaming_enabled": True,
    "reference_history_enabled": True,
    "save_new_memories": True,
    "auto_archive_enabled": True,
    "use_archived_memories": False,
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
    ) -> int:
        return self._insert_memory(
            scope=scope,
            kind=kind,
            text=text,
            status="pending",
            source_thread_id=source_thread_id,
            confidence=confidence,
        )

    def save_memory(
        self,
        *,
        kind: str,
        text: str,
        source_thread_id: str,
        confidence: float,
        scope: str = "global",
    ) -> int:
        memory_id = self._insert_memory(
            scope=scope,
            kind=kind,
            text=text,
            status="saved",
            source_thread_id=source_thread_id,
            confidence=confidence,
        )
        self.audit("saved", memory_id, text)
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
    ) -> int:
        now = self._now()
        clean_scope = _normalize_scope(scope)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memory_items (
                    scope, kind, text, status, source_thread_id, confidence, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (clean_scope, kind, text, status, source_thread_id, float(confidence), now, now),
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
        with self._connect() as conn:
            conn.execute("DELETE FROM memory_items WHERE id = ?", (int(memory_id),))
        self.audit("deleted", memory_id, item["text"])

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
                "UPDATE memory_items SET text = ?, kind = ?, updated_at = ? WHERE id = ?",
                (next_text, next_kind, now, int(memory_id)),
            )
        updated = self.get_memory(memory_id)
        self.audit("updated", memory_id, updated["text"])
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

    def get_settings(self) -> dict[str, bool]:
        settings = dict(DEFAULT_MEMORY_SETTINGS)
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM memory_settings").fetchall()
        for row in rows:
            if row["key"] not in settings:
                continue
            try:
                settings[row["key"]] = bool(json.loads(row["value"]))
            except json.JSONDecodeError:
                settings[row["key"]] = row["value"].lower() == "true"
        return settings

    def update_settings(self, patch: dict[str, Any]) -> dict[str, bool]:
        allowed = set(DEFAULT_MEMORY_SETTINGS)
        now = self._now()
        with self._connect() as conn:
            for key, value in patch.items():
                if key not in allowed:
                    continue
                conn.execute(
                    """
                    INSERT INTO memory_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (key, json.dumps(bool(value)), now),
                )
        self.audit("settings_updated", None, json.dumps({k: bool(v) for k, v in patch.items() if k in allowed}, sort_keys=True))
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

    def __post_init__(self) -> None:
        if self.store is None:
            self.store = SQLiteMemoryStore()
        self.memory_dir = Path(self.memory_dir)
        if self.provider_extensions is None:
            self.provider_extensions = build_default_memory_provider_extensions()

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
    ) -> dict[str, Any]:
        clean_query = query.strip()
        clean_answer = answer.strip()
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

        memory_card_path = ""
        if confidence >= 0.85:
            card = self.memory_service.create_card(
                {
                    "scope": _scope_for_agent(agent_name),
                    "title": _card_title(clean_query),
                    "summary": clean_answer,
                    "evidence": _evidence_text(compact_tools, source_list),
                    "visible_to": ["VellumAgent", "MemoryAgent", agent_name],
                }
            )
            memory_card_path = str(card.get("path") or "")

        if self.honcho is not None:
            session_id = self.honcho.get_or_create_session(thread_id)
            self.honcho.add_message(session_id, content=clean_query, role="user")
            self.honcho.add_message(session_id, content=clean_answer, role="assistant")

        external_sync = []
        if self.provider_extensions is not None:
            external_sync = self.provider_extensions.sync_turn(
                clean_query,
                clean_answer,
                session_id=thread_id,
                metadata={
                    "agent_name": agent_name,
                    "tools": compact_tools,
                    "sources": source_list,
                    "confidence": confidence,
                },
            )

        return {
            "stored": True,
            "fts5_id": rowid,
            "resolved_cached": resolved_cached,
            "memory_card_path": memory_card_path,
            "external_sync": external_sync,
        }

    def build_memory_packet(
        self,
        *,
        thread_id: str,
        query: str,
        agent_name: str = "VellumAgent",
        active_project: str | None = None,
        cloud_safe: bool = False,
    ) -> dict[str, Any]:
        clean_query = query.strip()
        scopes = _packet_scopes(agent_name=agent_name, active_project=active_project)
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
        if self.store is not None:
            baseline_scopes = [scope for scope in scopes if scope in {"global", "user_profile"} or scope.startswith("project:")]
            baseline = self.store.list_saved(scopes=baseline_scopes)[:4] if baseline_scopes else []
            matched = self.store.search_saved(clean_query, limit=8, scopes=scopes)
            saved = _dedupe_memories([*baseline, *matched])[:8]
        docs = self.fts5.search(_memory_search_query(clean_query), limit=5) if settings.get("reference_history_enabled", True) else []
        honcho_context = ""
        if self.honcho is not None:
            try:
                honcho_context = str(self.honcho.chat(session_id=thread_id, query=clean_query) or "")
            except Exception:
                honcho_context = ""
        docs = docs or (self.fts5.recent_documents(limit=5) if settings.get("reference_history_enabled", True) else [])
        external_context = self.provider_extensions.prefetch(clean_query, session_id=thread_id) if self.provider_extensions else []
        packet = {
            "global_summary": self.store.global_summary() if self.store is not None else "",
            "saved_memories": saved,
            "honcho_context": honcho_context,
            "project_context": self.store.project_summary(active_project) if self.store is not None else "",
            "recent_context": "\n\n".join(str(doc.get("content") or "") for doc in docs[:3]),
            "external_context": "\n\n".join(item["context"] for item in external_context if item.get("context")),
            "external_providers": external_context,
            "scopes": scopes,
            "settings": settings,
        }
        if cloud_safe:
            packet = _scrub_packet(packet)
        return packet

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
        stored: list[dict[str, Any]] = []
        scope = _scope_for_agent(agent_name)
        for candidate in candidates:
            data_class, _reason = classify(candidate["text"])
            if data_class == DataClass.RED and not _explicit_remember(user_message):
                continue
            memory_id = self.store.add_pending(
                kind=candidate["kind"],
                text=candidate["text"],
                source_thread_id=thread_id,
                confidence=candidate["confidence"],
                scope=scope,
            )
            item = self.store.get_memory(memory_id)
            self.store.audit("pending_created", memory_id, f"{agent_name}: {candidate['text']}")
            stored.append(item)
        return stored

    def run_dreaming(self, *, stale_days: int = 30) -> dict[str, Any]:
        if self.store is None:
            return _empty_dream()
        new_memories: list[dict[str, Any]] = []
        updated_memories: list[dict[str, Any]] = []
        archived_memories: list[dict[str, Any]] = []
        contradictions: list[dict[str, Any]] = []

        seen_texts = {_norm(item["text"]) for item in self.store.list_saved()}
        for pending in self.store.list_pending():
            key = _norm(pending["text"])
            if key in seen_texts:
                archived_memories.append(self.store.archive(pending["id"]))
                continue
            promoted = self.store.promote(pending["id"])
            new_memories.append(promoted)
            seen_texts.add(key)

        saved = self.store.list_saved()
        for left_index, left in enumerate(saved):
            for right in saved[left_index + 1 :]:
                if _simple_contradiction(left["text"], right["text"]):
                    contradictions.append({"left": left, "right": right})

        cutoff = datetime.now(UTC) - timedelta(days=max(0, int(stale_days)))
        for item in saved:
            if item["pinned"]:
                continue
            if datetime.fromisoformat(item["updated_at"]) <= cutoff:
                archived_memories.append(self.store.archive(item["id"]))

        global_summary = _summarize_memories(self.store.list_saved())
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

    def import_obsidian_memories(self, vault_root: str | Path) -> dict[str, Any]:
        if self.store is None:
            return {"imported_count": 0, "skipped_count": 0, "memories": []}
        root = Path(vault_root)
        candidates: list[tuple[Path, str]] = []
        for folder in ("Agent/Memories", "Agent/Saved"):
            base = root / folder
            if base.exists():
                candidates.extend((path, folder) for path in sorted(base.rglob("*.md")) if path.is_file())

        existing_sources = {str(item.get("source_thread_id") or "") for item in self.store.list_saved()}
        existing_texts = {_norm(str(item.get("text") or "")) for item in self.store.list_saved()}
        imported: list[dict[str, Any]] = []
        skipped = 0
        for path, folder in candidates:
            rel = path.relative_to(root).as_posix()
            if rel in existing_sources:
                skipped += 1
                continue
            text = _memory_text_from_markdown(path)
            if not text:
                skipped += 1
                continue
            key = _norm(text)
            if key in existing_texts:
                skipped += 1
                continue
            memory_id = self.store.save_memory(
                kind="imported",
                text=text,
                source_thread_id=rel,
                confidence=0.82,
                scope="global" if folder.endswith("Memories") else "user_profile",
            )
            item = self.store.get_memory(memory_id)
            imported.append(item)
            existing_texts.add(key)
            existing_sources.add(rel)
        self.store.audit("obsidian_import_completed", None, f"imported={len(imported)} skipped={skipped}")
        return {"imported_count": len(imported), "skipped_count": skipped, "memories": imported}


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
    text = user_message.strip()
    if not text:
        return []
    candidates: list[dict[str, Any]] = []
    explicit = re.search(
        r"\b(?:remember|memorize|note|keep in mind)\b(?:\s+that)?\s+(?P<fact>.+)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if explicit:
        fact = explicit.group("fact")
        candidates.append({"kind": _candidate_kind(fact), "text": _sentence(fact), "confidence": 0.92})
    if re.search(r"\b(?:i prefer|i like|i don't like|i do not like|stop adding|don't include|do not include)\b", text, re.I):
        candidates.append({"kind": "preference", "text": _sentence(text), "confidence": 0.82})
    if re.search(r"\b(?:vellum|project|we decided|decision|architecture|backend|frontend)\b", text, re.I):
        candidates.append({"kind": "project", "text": _sentence(text), "confidence": 0.7})
    return _dedupe_candidates(candidates)


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


def _memory_text_from_markdown(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    text = re.sub(r"\A---\s*.*?\s*---", "", raw, flags=re.DOTALL).strip()
    lines = []
    for line in text.splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue
        lines.append(re.sub(r"^[-*]\s+", "", clean))
    return _squash(" ".join(lines), limit=1200)


def _explicit_remember(text: str) -> bool:
    return bool(re.search(r"\b(?:remember|memorize|note|keep in mind)\b", text, re.I))


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
    scopes = ["global", "user_profile"]
    if active_project:
        scopes.append(f"project:{_normalize_scope(active_project)}")
    scopes.append(_agent_scope(agent_name))
    return list(dict.fromkeys(scopes))


def _scope_for_agent(agent_name: str) -> str:
    return _agent_scope(agent_name)


def _card_title(query: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", query)
    return " ".join(words[:10]) or "Resolved turn"


def _squash(text: str, *, limit: int) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"
