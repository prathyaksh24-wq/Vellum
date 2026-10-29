"""Main-model delegation tool for Vellum's Discord specialist."""

from __future__ import annotations

import json

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from agent.agents.base import SpecialistResponse
from agent.config import get_settings
from agent.master.live_runtime import get_delegation_runtime
from agent.master.runtime import DelegationRequest
from agent.master.state import MasterThreadStateStore


_pending_action_store = MasterThreadStateStore()


def _thread_id(config: RunnableConfig | None) -> str:
    configurable = config.get("configurable", {}) if config else {}
    thread_id = str(configurable.get("thread_id") or "").strip() if isinstance(configurable, dict) else ""
    return thread_id or get_settings().thread_id


def _persist_pending_action(response: SpecialistResponse, config: RunnableConfig | None) -> None:
    if not response.action_request or not config:
        return
    configurable = config.get("configurable", {})
    thread_id = str(configurable.get("thread_id") or "").strip() if isinstance(configurable, dict) else ""
    if thread_id:
        _pending_action_store.set_pending_action(thread_id, {"agent": response.agent, **response.action_request})


def _external_response_json(response: SpecialistResponse) -> str:
    action_request = response.action_request if isinstance(response.action_request, dict) else {}
    structured = response.structured_payload if isinstance(response.structured_payload, dict) else {}
    sent_message = structured.get("message") if isinstance(structured.get("message"), dict) else {}
    thread = structured.get("thread") if isinstance(structured.get("thread"), dict) else {}
    reaction = structured.get("reaction") if isinstance(structured.get("reaction"), dict) else {}
    if action_request:
        summary = "DiscordAgent prepared a Discord action that requires local confirmation."
    elif sent_message or thread or reaction:
        summary = "DiscordAgent completed a policy-controlled Discord action."
    elif response.sources:
        summary = f"DiscordAgent read {len(response.sources)} local-only Discord message(s)."
    else:
        summary = "DiscordAgent completed the request locally."
    payload = {
        "agent": response.agent,
        "status": response.status,
        "summary": summary,
        "analysis": "Raw Discord content is withheld from external model context.",
        "sources": [],
        "confidence": response.confidence,
        "memory_proposals": [],
        "activity_events": [],
        "structured_payload": {
            "authorization": str(structured.get("authorization") or ""),
            "action": str(structured.get("action") or ""),
            "message": {"sent": bool(sent_message)},
            "thread": {"created": bool(thread.get("id"))},
            "reaction": {"added": bool(reaction.get("added"))},
        } if sent_message or thread or reaction else {},
        "action_request": (
            {
                "action": str(action_request.get("action") or ""),
                "requires_confirmation": True,
            }
            if action_request
            else {}
        ),
        "privacy": "local_only_content_withheld",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def discord_agent(query: str, config: RunnableConfig | None = None) -> str:
    """Delegate Discord reads and bot actions to DiscordAgent.

    DiscordAgent owns installed-bot identity, server and channel reads, recent
    messages, and policy-controlled message, reaction, and thread actions. It
    never uses a user account token.
    """
    clean_query = str(query or "").strip()
    if not clean_query:
        return _external_response_json(SpecialistResponse(
            agent="DiscordAgent",
            status="blocked",
            summary="DiscordAgent requires a request.",
        ))
    try:
        response = get_delegation_runtime().delegate(
            DelegationRequest(
                agent_id="DiscordAgent",
                task=clean_query,
                parent_thread_id=_thread_id(config),
            )
        ).response
        _persist_pending_action(response, config)
        return _external_response_json(response)
    except Exception:
        return _external_response_json(SpecialistResponse(
            agent="DiscordAgent",
            status="error",
            summary="DiscordAgent is unavailable.",
            analysis="The specialist runtime failed before returning a response.",
        ))
