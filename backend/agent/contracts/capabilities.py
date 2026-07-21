"""Capability discovery contract for the Vellum frontend.

This module is intentionally data-shaped and dependency-light: the frontend
uses it to decide what to render, while backend implementations remain behind
their own services/plugins.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FeatureContract(BaseModel):
    enabled: bool
    contract: str = "v1"
    source: str
    plugin_owned: bool = False
    endpoints: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


class FrontendContract(BaseModel):
    canonical_entry: str
    api_adapter_namespace: str = "window.VellumApi"
    api_adapter_path: str = "/design-uploads/api"


class CapabilityContract(BaseModel):
    api_version: str = "v1"
    contract_version: int = 1
    frontend: FrontendContract
    features: dict[str, FeatureContract]
    stream_events: dict[str, list[str]]


def build_capability_contract() -> CapabilityContract:
    """Return the stable frontend/backend boundary for Vellum's web UI."""

    return CapabilityContract(
        frontend=FrontendContract(
            canonical_entry="/design-uploads/Vellum%20Default%20Re-designed.html",
        ),
        features={
            "chat": FeatureContract(
                enabled=True,
                source="backend.agent.api",
                endpoints={
                    "stream": "/api/chat/stream",
                    "turn": "/api/chat",
                    "models": "/api/models",
                },
            ),
            "conversation_library": FeatureContract(
                enabled=True,
                source="backend.agent.conversations",
                endpoints={
                    "list": "/api/conversations",
                    "library": "/api/conversations/library",
                    "search": "/api/conversations/search",
                    "organization": "/api/conversations/{conversation_id}/organization",
                    "rebuild": "/api/conversations/organization/rebuild",
                },
                notes="Local derived Spaces, topics, source facets, segments, and message-level search.",
            ),
            "plugins": FeatureContract(
                enabled=True,
                source="plugin_registry",
                plugin_owned=True,
                endpoints={
                    "list": "/api/plugins",
                    "skills": "/api/skills",
                    "capabilities": "/api/capabilities",
                },
            ),
            "spotify": FeatureContract(
                enabled=True,
                source="plugins/connectors/spotify",
                plugin_owned=True,
                endpoints={
                    "status": "/api/plugins/spotify/status",
                    "oauth_start": "/api/plugins/spotify/oauth/start",
                    "logout": "/api/plugins/spotify/logout",
                    "player": "/api/plugins/spotify/player",
                    "player_action": "/api/plugins/spotify/player/action",
                },
            ),
            "memory_orchestrator": FeatureContract(
                enabled=True,
                source="plugins/memory/vellum-memory-orchestrator",
                plugin_owned=True,
                endpoints={
                    "summary": "/api/memory/summary",
                    "saved": "/api/memory/saved",
                    "archived": "/api/memory/archived",
                    "settings": "/api/memory/settings",
                    "dreaming_run": "/api/memory/dreaming/run",
                    "import_conversations": "/api/memory/import-conversations",
                },
            ),
            "knowledge_wiki": FeatureContract(
                enabled=True,
                source="backend.agent.obsidian.wiki_api",
                endpoints={
                    "status": "/api/knowledge/status",
                    "query": "/api/knowledge/query",
                    "search": "/api/knowledge/search",
                    "vault_note": "/api/knowledge/vault-note",
                    "read_page": "/api/knowledge/pages/{ref}",
                    "conversation_context": "/api/conversations/{id}/context",
                    "history": "/api/knowledge/pages/{ref}/history",
                    "upsert_page": "/api/knowledge/pages",
                    "ingest": "/api/knowledge/ingest",
                    "overview": "/api/knowledge/overview",
                    "lint": "/api/knowledge/lint",
                    "rebuild_index": "/api/knowledge/rebuild-index",
                },
                notes="Private maintained knowledge; raw Library notes are never ingested automatically.",
            ),
            "personal_intelligence": FeatureContract(
                enabled=True,
                source="backend.agent.knowledge",
                endpoints={
                    "status": "/api/knowledge/core/status",
                    "ownership": "/api/knowledge/core/ownership",
                    "sources": "/api/knowledge/core/sources",
                    "observations": "/api/knowledge/core/observations",
                    "context_packs": "/api/knowledge/core/context-packs",
                    "bootstrap": "/api/knowledge/core/bootstrap",
                },
                notes="Cerebras-style canonical evidence layer operating in additive shadow mode.",
            ),
            "hermes_skills": FeatureContract(
                enabled=True,
                source="plugin_runtime.hermes",
                plugin_owned=True,
                endpoints={
                    "skills": "/api/skills",
                    "plugins": "/api/plugins",
                },
            ),
            "openrouter": FeatureContract(
                enabled=True,
                source="agent.llm.providers",
                endpoints={
                    "models": "/api/models",
                    "active_model": "/api/settings/active-model",
                    "provider_key": "/api/settings/provider-key",
                },
            ),
            "agent_runtime": FeatureContract(
                enabled=True,
                source="backend.agent.api",
                endpoints={
                    "subagents": "/api/subagents",
                },
            ),
        },
        stream_events={
            "chat": [
                "response.created",
                "response.output_item.added",
                "response.output_item.done",
                "response.output_text.delta",
                "response.function_call_arguments.delta",
                "response.function_call_arguments.done",
                "agent.activity",
                "response.completed",
                "response.failed",
                "error",
            ],
        },
    )


def public_capability_contract() -> dict[str, Any]:
    return build_capability_contract().model_dump()
