"""Core Memory Orchestrator tool for Vellum and sub-agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from agent.config import get_settings
from agent.memory.fts5 import FTS5Memory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
from agent.memory.resolved import ResolvedQuestionsCache
from agent.tools.capabilities.memory_service import MemoryCapabilityService


_ORCHESTRATOR: MemoryOrchestrator | None = None


def _default_orchestrator() -> MemoryOrchestrator:
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        settings = get_settings()
        _ORCHESTRATOR = MemoryOrchestrator(
            fts5=FTS5Memory(),
            resolved_cache=ResolvedQuestionsCache(),
            memory_service=MemoryCapabilityService(
                vault_root=settings.obsidian_vault_path,
                sessions_db=Path("data/memory/sessions.db"),
            ),
            store=SQLiteMemoryStore(Path("data/memory/sessions.db")),
        )
    return _ORCHESTRATOR


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def memory_orchestrator(
    action: str,
    query: str = "",
    text: str = "",
    thread_id: str = "default",
    agent_name: str = "VellumAgent",
    scope: str = "",
    memory_enabled: bool | None = None,
    dreaming_enabled: bool | None = None,
    reference_history_enabled: bool | None = None,
    save_new_memories: bool | None = None,
    auto_archive_enabled: bool | None = None,
    use_archived_memories: bool | None = None,
) -> str:
    """Inspect and operate Vellum's core memory system.

    Actions: status, settings, update_settings, summary, search, build_packet,
    save_candidate, run_dreaming, list_saved, list_archived.
    Use this for Dreaming status, memory toggles, memory summary, and explicit
    requests to run memory consolidation.
    """

    orchestrator = _default_orchestrator()
    store = orchestrator.store
    normalized = action.strip().casefold().replace("-", "_")
    if store is None:
        return _json({"action": normalized, "ok": False, "error": "memory store unavailable"})

    if normalized in {"status", "settings"}:
        settings = store.get_settings()
        return _json(
            {
                "action": normalized,
                "ok": True,
                "settings": settings,
                "saved_count": len(store.list_saved()),
                "pending_count": len(store.list_pending()),
                "archived_count": len(store.list_archived()),
                "global_summary": store.global_summary(),
            }
        )

    if normalized == "update_settings":
        patch = {
            "memory_enabled": memory_enabled,
            "dreaming_enabled": dreaming_enabled,
            "reference_history_enabled": reference_history_enabled,
            "save_new_memories": save_new_memories,
            "auto_archive_enabled": auto_archive_enabled,
            "use_archived_memories": use_archived_memories,
        }
        return _json({"action": normalized, "ok": True, "settings": store.update_settings({k: v for k, v in patch.items() if v is not None})})

    if normalized == "summary":
        return _json(
            {
                "action": normalized,
                "ok": True,
                "global_summary": store.global_summary(),
                "saved_memories": store.list_saved(),
                "archived_memories": store.list_archived(),
                "pending_count": len(store.list_pending()),
                "audit_log": store.audit_log(limit=25),
            }
        )

    if normalized == "search":
        scopes = [scope] if scope else None
        clean_query = query or text
        terms = []
        for term in clean_query.casefold().replace("*", " ").split():
            stripped = "".join(ch for ch in term if ch.isalnum())
            if (
                len(stripped) > 2
                or (len(stripped) == 2 and any(ch.isdigit() for ch in stripped))
            ) and stripped not in {"what", "when", "where", "from", "chat", "chats", "previous", "about"}:
                terms.append(stripped)
        fts_query = " OR ".join(dict.fromkeys(terms)) or clean_query
        return _json(
            {
                "action": normalized,
                "ok": True,
                "memories": store.search_saved(clean_query, scopes=scopes, limit=8),
                "indexed_conversation_hits": orchestrator.fts5.search(fts_query, limit=8),
            }
        )

    if normalized == "build_packet":
        return _json(
            {
                "action": normalized,
                "ok": True,
                "packet": orchestrator.build_memory_packet(
                    thread_id=thread_id,
                    query=query or text,
                    agent_name=agent_name,
                    cloud_safe=True,
                ),
            }
        )

    if normalized == "save_candidate":
        clean_text = text.strip() or query.strip()
        if not clean_text:
            return _json({"action": normalized, "ok": False, "error": "save_candidate requires text"})
        memory_id = store.add_pending(
            kind="fact",
            text=clean_text,
            source_thread_id=thread_id,
            confidence=0.8,
            scope=scope or f"agent:{agent_name}",
        )
        return _json({"action": normalized, "ok": True, "memory": store.get_memory(memory_id)})

    if normalized == "run_dreaming":
        return _json({"action": normalized, "ok": True, **orchestrator.run_dreaming()})

    if normalized == "import_obsidian":
        return _json({"action": normalized, "ok": True, **orchestrator.import_obsidian_memories(get_settings().obsidian_vault_path)})

    if normalized == "list_saved":
        return _json({"action": normalized, "ok": True, "memories": store.list_saved(scopes=[scope] if scope else None)})

    if normalized == "list_archived":
        return _json({"action": normalized, "ok": True, "memories": store.list_archived(scopes=[scope] if scope else None)})

    return _json(
        {
            "action": normalized,
            "ok": False,
            "error": "Unsupported memory action. Use status, settings, update_settings, summary, search, build_packet, save_candidate, run_dreaming, list_saved, or list_archived.",
        }
    )
