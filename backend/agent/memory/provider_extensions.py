"""Optional external memory provider extensions for Vellum.

These providers extend the local Memory Orchestrator. They never replace the
core SQLite/FTS5/Chroma/Honcho/Obsidian stack.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol


class MemoryProviderExtension(Protocol):
    id: str
    name: str
    provider_type: str
    optional: bool
    capabilities: list[str]

    def is_enabled(self) -> bool: ...

    def is_configured(self) -> bool: ...

    def setup_notes(self) -> str: ...


@dataclass(slots=True)
class ConfiguredMemoryProviderExtension:
    id: str
    name: str
    provider_type: str
    env_key: str
    enable_key: str = "MEMORY_EXTENSION_PROVIDERS"
    optional: bool = True
    capabilities: list[str] = field(default_factory=list)
    notes: str = ""

    def is_enabled(self) -> bool:
        enabled = _enabled_provider_ids()
        if self.id in enabled:
            return True
        explicit_flag = os.environ.get(f"{self.id.upper()}_MEMORY_ENABLED", "")
        return explicit_flag.strip().lower() in {"1", "true", "yes", "on"}

    def is_configured(self) -> bool:
        return bool(os.environ.get(self.env_key, "").strip())

    def setup_notes(self) -> str:
        return self.notes or f"Set {self.env_key} and add {self.id} to MEMORY_EXTENSION_PROVIDERS."


class HolographicProviderExtension(ConfiguredMemoryProviderExtension):
    def __init__(self) -> None:
        super().__init__(
            id="holographic",
            name="Holographic Memory",
            provider_type="local_structured_facts",
            env_key="HOLOGRAPHIC_MEMORY_ENABLED",
            capabilities=["memory.prefetch", "memory.mirror_write", "fact.search", "fact.feedback"],
            notes="Set HOLOGRAPHIC_MEMORY_ENABLED=true and add holographic to MEMORY_EXTENSION_PROVIDERS.",
        )

    def is_configured(self) -> bool:
        return os.environ.get("HOLOGRAPHIC_MEMORY_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


class MemoryProviderExtensionManager:
    def __init__(self, providers: list[MemoryProviderExtension] | None = None) -> None:
        self.providers = providers or []

    def statuses(self) -> list[dict[str, Any]]:
        return [_status_for(provider) for provider in self.providers]

    def active_provider_ids(self) -> list[str]:
        return [provider.id for provider in self.providers if provider.is_enabled() and provider.is_configured()]


def build_default_memory_provider_extensions() -> MemoryProviderExtensionManager:
    return MemoryProviderExtensionManager(
        [
            ConfiguredMemoryProviderExtension(
                id="hindsight",
                name="Hindsight",
                provider_type="knowledge_graph",
                env_key="HINDSIGHT_API_KEY",
                capabilities=["memory.prefetch", "memory.sync_turn", "memory.reflect", "memory.recall"],
                notes="Set HINDSIGHT_API_KEY and add hindsight to MEMORY_EXTENSION_PROVIDERS.",
            ),
            ConfiguredMemoryProviderExtension(
                id="supermemory",
                name="Supermemory",
                provider_type="managed_semantic_profile",
                env_key="SUPERMEMORY_API_KEY",
                capabilities=["memory.prefetch", "memory.sync_turn", "memory.profile", "memory.search"],
                notes="Set SUPERMEMORY_API_KEY and add supermemory to MEMORY_EXTENSION_PROVIDERS.",
            ),
            HolographicProviderExtension(),
        ]
    )


def _status_for(provider: MemoryProviderExtension) -> dict[str, Any]:
    enabled = provider.is_enabled()
    configured = provider.is_configured()
    status = "ready" if enabled and configured else "not_configured" if enabled else "disabled"
    return {
        "id": provider.id,
        "name": provider.name,
        "type": provider.provider_type,
        "optional": provider.optional,
        "enabled": enabled,
        "configured": configured,
        "status": status,
        "capabilities": list(provider.capabilities),
        "notes": "" if status == "ready" else provider.setup_notes(),
    }


def _enabled_provider_ids() -> set[str]:
    raw = os.environ.get("MEMORY_EXTENSION_PROVIDERS", "")
    return {part.strip().casefold() for part in raw.split(",") if part.strip()}
