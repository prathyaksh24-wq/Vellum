"""Process-wide Personal Intelligence runtime."""

from __future__ import annotations

from threading import Lock

from agent.config import REPO_ROOT, get_settings
from agent.knowledge.service import KnowledgeCore
from agent.knowledge.store import KnowledgeStore


_RUNTIME: KnowledgeCore | None = None
_LOCK = Lock()


def build_knowledge_core() -> KnowledgeCore:
    settings = get_settings()
    return KnowledgeCore(
        KnowledgeStore(settings.knowledge_core_db_path, settings.knowledge_blob_path),
        conversations_path=REPO_ROOT / "data" / "ui" / "conversations.json",
        vault_root=settings.obsidian_vault_path,
        shadow_write=settings.knowledge_shadow_write,
        read_enabled=settings.knowledge_read_enabled,
        tool_learning_enabled=settings.knowledge_tool_observation_learning,
    )


def get_knowledge_core() -> KnowledgeCore:
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME
    with _LOCK:
        if _RUNTIME is None:
            _RUNTIME = build_knowledge_core()
    return _RUNTIME


def set_knowledge_core(core: KnowledgeCore | None) -> None:
    global _RUNTIME
    with _LOCK:
        _RUNTIME = core
