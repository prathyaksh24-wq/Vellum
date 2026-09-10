"""Main-model delegation tool for Vellum's Calendar specialist."""

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


def _external_response_json(response: SpecialistResponse) -> str:
    action = response.action_request if isinstance(response.action_request, dict) else {}
    structured = response.structured_payload if isinstance(response.structured_payload, dict) else {}
    payload = {
        "agent": response.agent,
        "status": response.status,
        "summary": (
            "CalendarAgent prepared a Calendar change that requires local confirmation."
            if action
            else "CalendarAgent completed the Calendar request locally."
        ),
        "analysis": "Raw Calendar content is withheld from external model context.",
        "sources": [],
        "confidence": response.confidence,
        "memory_proposals": [],
        "activity_events": [],
        "structured_payload": {
            "authorization": str(structured.get("authorization") or ""),
            "action": str(structured.get("action") or ""),
            "changed": bool(structured),
        } if structured else {},
        "action_request": (
            {"action": str(action.get("action") or ""), "requires_confirmation": True}
            if action
            else {}
        ),
        "privacy": "local_only_content_withheld",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def calendar_agent(query: str, config: RunnableConfig | None = None) -> str:
    """Delegate private schedule reads and confirmed Google Calendar changes to CalendarAgent."""
    clean_query = str(query or "").strip()
    if not clean_query:
        return _external_response_json(SpecialistResponse(
            agent="CalendarAgent",
            status="blocked",
            summary="CalendarAgent requires a request.",
        ))
    try:
        response = get_delegation_runtime().delegate(DelegationRequest(
            agent_id="CalendarAgent",
            task=clean_query,
            parent_thread_id=_thread_id(config),
        )).response
        if response.action_request and config:
            configurable = config.get("configurable", {})
            thread_id = str(configurable.get("thread_id") or "").strip() if isinstance(configurable, dict) else ""
            if thread_id:
                _pending_action_store.set_pending_action(
                    thread_id,
                    {"agent": response.agent, **response.action_request},
                )
        return _external_response_json(response)
    except Exception:
        return _external_response_json(SpecialistResponse(
            agent="CalendarAgent",
            status="error",
            summary="CalendarAgent is unavailable.",
        ))
