"""Main-model delegation tool for BooksAgent."""
from __future__ import annotations

import json

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from agent.agents.base import SpecialistResponse
from agent.contracts.books import books_envelope_payload
from agent.config import get_settings
from agent.master.live_runtime import get_delegation_runtime
from agent.master.runtime import DelegationRequest


def _get_books_runtime():
    return get_delegation_runtime()


def _thread_id(config: RunnableConfig | None) -> str:
    configurable = config.get("configurable", {}) if config else {}
    thread_id = str(configurable.get("thread_id") or "").strip() if isinstance(configurable, dict) else ""
    return thread_id or get_settings().thread_id


def _user_id(config: RunnableConfig | None) -> str:
    configurable = config.get("configurable", {}) if config else {}
    user_id = str(configurable.get("user_id") or "").strip() if isinstance(configurable, dict) else ""
    return user_id or "default"


def _response_json(response: SpecialistResponse) -> str:
    payload = response.model_dump(mode="json")
    structured = payload.get("structured_payload")
    envelope = structured.get("books_agent") if isinstance(structured, dict) else None
    if isinstance(envelope, dict):
        envelope["user_learning_events"] = []
        envelope["wisdom_proposals"] = []
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def books_agent(query: str, config: RunnableConfig | None = None) -> str:
    """Delegate Book questions and Book-grounded reasoning to BooksAgent.

    Use this for questions about an installed Book, author ideas, chapters,
    quotations, comparisons, or vague references that may match a Hermes Book
    skill. BooksAgent owns Book skills and returns typed evidence or abstains.
    The main model must not activate Book skills directly.
    """
    clean_query = str(query or "").strip()
    if not clean_query:
        return _response_json(_tool_failure("blocked", "BooksAgent requires a question."))
    try:
        response = _get_books_runtime().delegate(
            DelegationRequest(
                agent_id="BooksAgent",
                task=clean_query,
                parent_thread_id=_thread_id(config),
                user_id=_user_id(config),
            )
        ).response
        return _response_json(response)
    except Exception:
        return _response_json(
            _tool_failure(
                "error",
                "BooksAgent is unavailable.",
                analysis="The specialist runtime failed before returning a response.",
            )
        )


def _tool_failure(status: str, summary: str, *, analysis: str = "") -> SpecialistResponse:
    return SpecialistResponse(
        agent="BooksAgent",
        status=status,
        summary=summary,
        analysis=analysis,
        confidence=0.0,
        structured_payload=books_envelope_payload(
            answer=summary,
            status="failed",
            uncertainty=["BooksAgent did not return a grounded answer."],
        ),
    )
