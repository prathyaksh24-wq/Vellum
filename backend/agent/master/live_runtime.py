"""Process-wide catalog and delegation runtime for first-class agents."""

from __future__ import annotations

from threading import Lock

from agent.config import get_settings
from agent.master.runtime import DelegationRuntime
from agent.master.state import MasterThreadStateStore
from agent.memory.runtime import get_memory_orchestrator
from agent.profiles import AgentCatalog


_RUNTIME: DelegationRuntime | None = None
_RUNTIME_LOCK = Lock()


def get_delegation_runtime() -> DelegationRuntime:
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            catalog = AgentCatalog.default(get_settings().obsidian_vault_path)
            _RUNTIME = DelegationRuntime(
                agent_catalog=catalog,
                memory_orchestrator=get_memory_orchestrator(),
                pending_action_store=MasterThreadStateStore(),
            )
    return _RUNTIME


def get_agent_catalog() -> AgentCatalog:
    return get_delegation_runtime().agent_catalog
