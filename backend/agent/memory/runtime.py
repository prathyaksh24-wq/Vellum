"""Process-wide runtime for Vellum's canonical Memory Orchestrator.

SQLite remains the durable system of record. FTS5, Chroma-backed memory
cards, Honcho, Obsidian projections, and optional providers are adapters
owned by this orchestrator rather than independent memory systems.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from agent.config import REPO_ROOT, get_settings
from agent.memory.fts5 import FTS5Memory
from agent.memory.honcho_client import HonchoMemory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
from agent.memory.resolved import ResolvedQuestionsCache
from agent.knowledge.runtime import get_knowledge_core
from agent.obsidian.wiki_runtime import get_knowledge_wiki
from agent.tools.capabilities.memory_service import MemoryCapabilityService


_RUNTIME: MemoryOrchestrator | None = None
_RUNTIME_LOCK = Lock()


def build_memory_orchestrator() -> MemoryOrchestrator:
    settings = get_settings()
    memory_root = REPO_ROOT / "data" / "memory"
    sessions_db = memory_root / "sessions.db"
    return MemoryOrchestrator(
        fts5=FTS5Memory(memory_root / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(memory_root / "resolved.db"),
        memory_service=MemoryCapabilityService(
            vault_root=settings.obsidian_vault_path,
            sessions_db=sessions_db,
        ),
        store=SQLiteMemoryStore(sessions_db),
        honcho=HonchoMemory(
            base_url=settings.honcho_base_url,
            app_id=settings.honcho_app_id,
            user_id=settings.honcho_user_id,
        ),
        memory_dir=memory_root,
        knowledge_wiki=get_knowledge_wiki(),
        knowledge_core=get_knowledge_core() if settings.knowledge_core_enabled else None,
    )


def get_memory_orchestrator() -> MemoryOrchestrator:
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            _RUNTIME = build_memory_orchestrator()
    return _RUNTIME


def set_memory_orchestrator(orchestrator: MemoryOrchestrator | None) -> None:
    """Override/reset the runtime for tests and controlled process teardown."""

    global _RUNTIME
    with _RUNTIME_LOCK:
        _RUNTIME = orchestrator
