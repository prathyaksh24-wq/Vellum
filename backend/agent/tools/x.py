"""Main-model delegation tool for Vellum's X specialist."""
from __future__ import annotations

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from agent.agents.base import SpecialistResponse
from agent.config import get_settings
from agent.master.live_runtime import get_delegation_runtime
from agent.master.runtime import DelegationRequest
from agent.master.state import MasterThreadStateStore


_pending_action_store = MasterThreadStateStore()


def _get_x_runtime():
    return get_delegation_runtime()


def _thread_id(config: RunnableConfig | None) -> str:
    configurable = config.get("configurable", {}) if config else {}
    thread_id = str(configurable.get("thread_id") or "").strip() if isinstance(configurable, dict) else ""
    return thread_id or get_settings().thread_id


def _response_json(response: SpecialistResponse) -> str:
    return response.model_dump_json(indent=2)


def _persist_pending_action(response: SpecialistResponse, config: RunnableConfig | None) -> None:
    action_request = response.action_request
    if not isinstance(action_request, dict) or not config:
        return
    configurable = config.get("configurable", {})
    thread_id = str(configurable.get("thread_id") or "").strip() if isinstance(configurable, dict) else ""
    if not thread_id:
        return
    _pending_action_store.set_pending_action(
        thread_id,
        {"agent": response.agent, **action_request},
    )


@tool
def x_agent(query: str, config: RunnableConfig | None = None) -> str:
    """Delegate an X/Twitter request to XAgent.

    Use this for X search, account status, timelines, bookmarks, likes, profiles,
    post reads, and requests to post, reply, like, repost, bookmark, follow, or
    delete. XAgent prepares external writes for Vellum's confirmation flow; this
    tool never treats a model-generated flag as user confirmation.
    """
    clean_query = str(query or "").strip()
    if not clean_query:
        return _response_json(
            SpecialistResponse(
                agent="XAgent",
                status="blocked",
                summary="XAgent requires a query.",
                confidence=0.0,
            )
        )
    try:
        response = _get_x_runtime().delegate(
            DelegationRequest(
                agent_id="XAgent",
                task=clean_query,
                parent_thread_id=_thread_id(config),
            )
        ).response
        _persist_pending_action(response, config)
        return _response_json(response)
    except Exception:
        return _response_json(
            SpecialistResponse(
                agent="XAgent",
                status="error",
                summary="XAgent is unavailable.",
                analysis="The specialist runtime failed before returning a response.",
                confidence=0.0,
            )
        )
