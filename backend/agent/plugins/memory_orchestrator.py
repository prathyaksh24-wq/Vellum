from __future__ import annotations

from typing import Any

from agent.memory.provider_extensions import build_default_memory_provider_extensions
from agent.plugins.models import PluginStatus


MEMORY_ORCHESTRATOR_CAPABILITIES = [
    "memory.status",
    "memory.search",
    "memory.build_packet",
    "memory.save_candidate",
    "memory.run_dreaming",
    "memory.list_saved",
    "memory.list_archived",
    "memory.get_settings",
    "memory.update_settings",
    "memory.import_obsidian",
    "memory.providers.status",
]


def memory_orchestrator_plugin_status(orchestrator: Any) -> PluginStatus:
    store = getattr(orchestrator, "store", None)
    if store is None:
        return _status(
            configured=False,
            status="error",
            notes="Memory Orchestrator is unavailable because SQLite memory store is not configured.",
        )

    try:
        saved_count = len(store.list_saved())
        pending_count = len(store.list_pending())
        archived_count = len(store.list_archived())
    except Exception as exc:
        return _status(
            configured=False,
            status="error",
            notes=f"Memory Orchestrator store health check failed: {str(exc)[:240]}",
        )

    degraded: list[str] = []
    honcho = getattr(orchestrator, "honcho", None)
    honcho_ready = bool(honcho is not None and getattr(honcho, "available", False))
    if not honcho_ready:
        degraded.append("Honcho is unreachable; SQLite/FTS5 memory remains available.")

    if degraded:
        return _status(
            configured=True,
            status="degraded",
            notes=" ".join(degraded) + f" Saved={saved_count}, pending={pending_count}, archived={archived_count}.",
            honcho_ready=honcho_ready,
        )

    return _status(
        configured=True,
        status="ready",
        notes=f"Memory Orchestrator is ready. Saved={saved_count}, pending={pending_count}, archived={archived_count}.",
        honcho_ready=honcho_ready,
    )


def _status(
    *,
    configured: bool,
    status: str,
    notes: str,
    honcho_ready: bool = False,
) -> PluginStatus:
    return PluginStatus(
        id="memory-orchestrator",
        name="Memory Orchestrator",
        type="system",
        category="Memory",
        configured=configured,
        status=status,
        notes=notes,
        capabilities=list(MEMORY_ORCHESTRATOR_CAPABILITIES),
        required=True,
        metadata={
            "providers": _provider_statuses(honcho_ready=honcho_ready),
            "external_extensions": build_default_memory_provider_extensions().statuses(),
        },
    )


def _provider_statuses(*, honcho_ready: bool) -> list[dict[str, Any]]:
    return [
        {
            "id": "sqlite",
            "name": "SQLite Memory Store",
            "type": "system_of_record",
            "status": "ready",
            "capabilities": ["memory.write", "memory.saved", "memory.archived", "memory.settings"],
        },
        {
            "id": "fts5",
            "name": "FTS5 Session Search",
            "type": "exact_search",
            "status": "ready",
            "capabilities": ["memory.search", "session.search", "recent_context"],
        },
        {
            "id": "chroma",
            "name": "Chroma Semantic Memory",
            "type": "semantic",
            "status": "ready",
            "capabilities": ["semantic_recall", "rag_context"],
        },
        {
            "id": "honcho",
            "name": "Honcho User Model",
            "type": "user_model",
            "status": "ready" if honcho_ready else "degraded",
            "capabilities": ["user_profile", "conversation_modeling"],
            "notes": (
                "Local Honcho API is reachable."
                if honcho_ready
                else "Start the local Honcho stack to enable user-model context."
            ),
        },
        {
            "id": "obsidian",
            "name": "Obsidian Memory Files",
            "type": "human_readable",
            "status": "ready",
            "capabilities": ["memory_cards", "USER.md", "MEMORY.md", "vault_import"],
        },
    ]
