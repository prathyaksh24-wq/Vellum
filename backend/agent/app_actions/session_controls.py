"""Conversation-scoped agent, model, reasoning, and memory controls."""

from __future__ import annotations

from typing import Any

from agent.app_actions.models import AppActionContext
from agent.llm.providers import ProviderRegistry
from agent.llm.reasoning import resolve_reasoning_mode
from agent.master.state import MasterThreadStateStore
from agent.profiles import AgentCatalog


AGENT_SELECT_ACTION_ID = "agent.select"
MODEL_SELECT_ACTION_ID = "model.select"
REASONING_SET_ACTION_ID = "reasoning.set"
MEMORY_CONVERSATION_SET_ACTION_ID = "memory.conversation.set"


class SessionControlError(ValueError):
    def __init__(self, code: str, message: str, *, unavailable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.unavailable = unavailable


class SessionControlService:
    """Apply chat controls through their existing canonical state owners."""

    _AGENT_ALIASES = {
        "vellum": "VellumAgent",
        "vellumagent": "VellumAgent",
        "x": "XAgent",
        "xagent": "XAgent",
        "twitter": "XAgent",
        "youtube": "YoutubeAgent",
        "youtubeagent": "YoutubeAgent",
        "sports": "SportsAgent",
        "sportsagent": "SportsAgent",
        "books": "BooksAgent",
        "booksagent": "BooksAgent",
        "research": "ResearchAgent",
        "researchagent": "ResearchAgent",
        "memory": "MemoryAgent",
        "memoryagent": "MemoryAgent",
    }

    def __init__(
        self,
        *,
        agent_catalog: AgentCatalog,
        state_store: MasterThreadStateStore,
        provider_registry: ProviderRegistry,
    ) -> None:
        self.agent_catalog = agent_catalog
        self.state_store = state_store
        self.provider_registry = provider_registry

    def execute(
        self,
        action_id: str,
        arguments: dict[str, Any],
        context: AppActionContext,
    ) -> dict[str, Any]:
        thread_id = str(context.invocation_conversation_id or "").strip()
        if not thread_id:
            raise SessionControlError(
                "CONVERSATION_CONTEXT_REQUIRED",
                "Choose or start a chat before changing this setting.",
            )
        if action_id == AGENT_SELECT_ACTION_ID:
            return self._select_agent(thread_id, arguments)
        if action_id == MODEL_SELECT_ACTION_ID:
            return self._select_model(thread_id, arguments)
        if action_id == REASONING_SET_ACTION_ID:
            return self._set_reasoning(thread_id, arguments)
        if action_id == MEMORY_CONVERSATION_SET_ACTION_ID:
            return self._set_memory(thread_id, arguments)
        raise SessionControlError("ACTION_UNAVAILABLE", f"{action_id} is unavailable.", unavailable=True)

    def _select_agent(self, thread_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = str(arguments.get("agent_id") or arguments.get("agent") or "").strip()
        agent_id = self._resolve_agent_id(raw)
        binding = None if not agent_id or agent_id == "VellumAgent" else self.agent_catalog.try_resolve(agent_id)
        unavailable = agent_id != "VellumAgent" and (
            binding is None
            or (binding.profile.executor == "deterministic" and binding.executor is None)
        )
        if not agent_id or unavailable:
            raise SessionControlError(
                "AGENT_UNAVAILABLE",
                f"{raw or 'That agent'} is not available in this Vellum installation.",
                unavailable=True,
            )
        previous = self.state_store.get(thread_id).active_agent
        self.state_store.set_active_agent(thread_id, agent_id, selected=agent_id != "VellumAgent")
        client_id = self._client_agent_id(agent_id)
        return {
            "changed": previous != agent_id,
            "active_agent": agent_id,
            "previous_active_agent": previous,
            "session_control_patch": {"agent_id": client_id},
            "target_kind": "conversation_runtime",
            "target_id": thread_id,
            "message": "Main Vellum agent selected." if agent_id == "VellumAgent" else f"{agent_id.removesuffix('Agent')} Agent selected.",
        }

    def _resolve_agent_id(self, raw: str) -> str:
        normalized = self._normalize_agent_name(raw)
        alias = self._AGENT_ALIASES.get(normalized)
        if alias is not None:
            return alias
        matches = [
            profile.id
            for profile in self.agent_catalog.list()
            if normalized in {
                self._normalize_agent_name(profile.id),
                self._normalize_agent_name(profile.id.removesuffix("Agent")),
            }
        ]
        return matches[0] if len(matches) == 1 else ""

    @staticmethod
    def _client_agent_id(agent_id: str) -> str:
        return agent_id.removesuffix("Agent").casefold()

    @staticmethod
    def _normalize_agent_name(value: str) -> str:
        return "".join(character for character in value.casefold() if character.isalnum())

    def _select_model(self, thread_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        requested = str(arguments.get("model_id") or arguments.get("model") or "").strip()
        entry = self.provider_registry.resolve(requested)
        available_ids = {model.id for model in self.provider_registry.list_models()}
        if entry is None or entry.id not in available_ids:
            raise SessionControlError(
                "MODEL_UNAVAILABLE",
                f"{requested or 'That model'} is not available with the current provider configuration.",
                unavailable=True,
            )
        previous = self.state_store.get(thread_id).selected_model
        self.state_store.set_selected_model(thread_id, entry.id)
        return {
            "changed": previous != entry.id,
            "model": {"id": entry.id, "label": entry.label, "provider": entry.provider},
            "previous_model_id": previous,
            "session_control_patch": {"model_id": entry.id},
            "turn_overrides": {"model": entry.id},
            "target_kind": "conversation_runtime",
            "target_id": thread_id,
            "message": f"Model set to {entry.label} for this chat.",
        }

    def _set_reasoning(self, thread_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = str(arguments.get("mode") or "").strip()
        if raw.casefold() in {"default", "standard", "off"}:
            raw = ""
        try:
            mode = resolve_reasoning_mode(raw)
        except ValueError as exc:
            raise SessionControlError("REASONING_MODE_UNAVAILABLE", str(exc), unavailable=True) from exc
        value = mode.value if mode is not None else ""
        previous = self.state_store.get(thread_id).reasoning_mode
        self.state_store.set_reasoning_mode(thread_id, value)
        return {
            "changed": previous != value,
            "reasoning_mode": value,
            "previous_reasoning_mode": previous,
            "session_control_patch": {"reasoning_mode": value},
            "turn_overrides": {"reasoning_mode": value},
            "target_kind": "conversation_runtime",
            "target_id": thread_id,
            "message": f"Reasoning set to {value}." if value else "Default reasoning restored.",
        }

    def _set_memory(self, thread_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        enabled = arguments.get("enabled")
        if not isinstance(enabled, bool):
            raise SessionControlError("INVALID_ACTION_ARGUMENTS", "enabled must be a boolean")
        previous = self.state_store.get(thread_id).store_to_memory
        self.state_store.set_store_to_memory(thread_id, enabled)
        return {
            "changed": previous != enabled,
            "store_to_memory": enabled,
            "previous_store_to_memory": previous,
            "session_control_patch": {"store_to_memory": enabled},
            "turn_overrides": {"store": enabled},
            "target_kind": "conversation_runtime",
            "target_id": thread_id,
            "message": "Memory is on for this chat." if enabled else "Memory is off for this chat.",
        }
