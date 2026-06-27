"""Hermes-style portable wrapper for Vellum's Memory Orchestrator."""

from __future__ import annotations

from agent.memory.orchestrator import MemoryOrchestrator
from agent.memory.provider_extensions import build_default_memory_provider_extensions
from agent.plugins.memory_orchestrator import memory_orchestrator_plugin_status


def register(ctx) -> None:
    ctx.register_system_plugin(
        id="memory-orchestrator",
        name="Vellum Memory Orchestrator",
        category="Memory",
        required=True,
        status_factory=memory_orchestrator_plugin_status,
        implementation=MemoryOrchestrator,
        capabilities=[
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
        ],
    )
    ctx.register_memory_provider(
        id="vellum-memory-extensions",
        name="Vellum External Memory Extensions",
        category="Memory",
        provider_factory=build_default_memory_provider_extensions,
        capabilities=[
            "memory.prefetch",
            "memory.sync_turn",
            "memory.provider_status",
        ],
    )
