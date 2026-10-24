"""Typed main-agent entry point into the shared specialist runtime."""

from __future__ import annotations

import json
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field, create_model

from agent.agents.base import SpecialistResponse
from agent.config import get_settings
from agent.master.live_runtime import get_delegation_runtime, get_agent_catalog
from agent.master.runtime import DelegationRequest


class DelegateToAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=80, description="Specialist profile ID from the directory.")
    task: str = Field(min_length=1, max_length=4000, description="One clear, bounded task for the specialist.")
    context: str = Field(
        default="",
        max_length=8000,
        description="Only the minimum user-provided context needed; never copy the whole conversation.",
    )
    memory_from: list[str] = Field(default_factory=list, max_length=4,
        description="Optional source profile IDs for relevant memory packets. The owner checks both agents' policies; never paste their chat history.")


def _thread_id(config: RunnableConfig | None) -> str:
    configurable = config.get("configurable", {}) if config else {}
    thread_id = str(configurable.get("thread_id") or "").strip() if isinstance(configurable, dict) else ""
    return thread_id or get_settings().thread_id


def _user_id(config: RunnableConfig | None) -> str:
    configurable = config.get("configurable", {}) if config else {}
    user_id = str(configurable.get("user_id") or "").strip() if isinstance(configurable, dict) else ""
    return user_id or "default"


def _response_payload(profile, response: SpecialistResponse) -> dict:
    payload = response.model_dump(mode="json")
    action = payload.get("action_request")
    if isinstance(action, dict) and action:
        payload["action_request"] = {
            "action": str(action.get("action") or ""),
            "requires_confirmation": True,
        }

    if profile.result_visibility == "summary":
        return {
            "agent": response.agent,
            "status": response.status,
            "summary": (
                f"{profile.id} prepared a change that requires local confirmation."
                if action
                else (
                    f"{profile.id} completed the request; private content is withheld from the main model."
                    if response.status == "answered"
                    else f"{profile.id} returned {response.status}; the requested action is not confirmed as completed. Private details are withheld from the main model."
                )
            ),
            "confidence": response.confidence,
            "action_request": payload.get("action_request", {}),
            "privacy": "summary_only",
        }

    if profile.response_schema == "books-agent-response-v1":
        structured = payload.get("structured_payload")
        envelope = structured.get("books_agent") if isinstance(structured, dict) else None
        if isinstance(envelope, dict):
            envelope["user_learning_events"] = []
            envelope["wisdom_proposals"] = []
    return payload


@tool(args_schema=DelegateToAgentInput)
def delegate_to_agent(
    agent_id: str,
    task: str,
    context: str = "",
    memory_from: list[str] | None = None,
    config: RunnableConfig = None,
) -> str:
    """Delegate only to an existing specialist profile in the directory. Plugins and MCP servers are not agents; use their tools directly or find them with tool_search."""
    clean_agent_id = str(agent_id or "").strip()
    clean_task = str(task or "").strip()
    clean_context = str(context or "").strip()
    runtime = get_delegation_runtime()
    binding = runtime.agent_catalog.try_resolve(clean_agent_id)
    if binding is None or not binding.profile.delegation.can_receive:
        return json.dumps(
            {"agent": clean_agent_id, "status": "blocked", "summary": "That specialist is not available. Use tool_search to find tools for this task; do not invent a profile from a plugin or service name."},
            ensure_ascii=False,
        )

    run = runtime.delegate(
        DelegationRequest(
            agent_id=clean_agent_id,
            task=clean_task,
            parent_thread_id=_thread_id(config),
            user_id=_user_id(config),
            context=clean_context,
            memory_from=tuple(memory_from or ()),
        )
    )
    response = run.response
    if response.action_request and runtime.pending_action_store is not None:
        stored = runtime.pending_action_store.set_pending_action(
            _thread_id(config),
            {"agent": response.agent, **response.action_request},
            replace=False,
        )
        if not stored:
            response = response.model_copy(
                update={
                    "status": "blocked",
                    "summary": "Resolve the existing pending action before preparing another change.",
                    "action_request": {},
                }
            )

    return json.dumps(_response_payload(binding.profile, response), ensure_ascii=False, indent=2)


def available_delegation_tool(catalog=None):
    """Constrain the advertised schema to the same catalog used for delegation."""
    ids=tuple(sorted({entry['id'] for entry in (catalog or get_agent_catalog()).delegation_manifest()}))
    if not ids:return None
    schema=create_model('AvailableSpecialistInput',__base__=DelegateToAgentInput,
        agent_id=(Literal[ids],Field(description="An existing specialist profile ID. For plugin/MCP tasks without a listed owner, use tool_search instead.")))
    return delegate_to_agent.model_copy(update={"args_schema":schema,
        "handle_validation_error":"That specialist is not listed. Use tool_search for plugin and MCP capabilities instead of inventing an agent."})
