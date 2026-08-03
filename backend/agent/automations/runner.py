"""Run-now execution for automations.

Records the run, executes a full reasoning turn through the same agent path
interactive chat uses (model profile + reasoning mode applied), delivers the
result to the destination (append into the pinned thread for ``existing_chat``,
a new conversation in the UI feed for ``new_chat``), and writes the outcome to
run history. Failures are recorded with the error surfaced; they never crash
the API. Scheduled fires and the skip-if-busy / full-access gates live in
``agent.automations.scheduler``.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from agent.automations.store import AutomationStore

logger = logging.getLogger(__name__)


def _run_id() -> str:
    return f"run-{uuid4().hex[:16]}"


async def run_automation_now(
    automation: dict[str, Any],
    store: AutomationStore,
) -> dict[str, Any]:
    run = store.record_run(automation["id"], _run_id())
    try:
        answer = await _execute_reasoning_turn(automation)
        _deliver_result(automation, answer)
        return store.finish_run(automation["id"], run["id"], status="complete", output=answer)
    except Exception as exc:
        return store.finish_run(automation["id"], run["id"], status="failed", error=str(exc))


async def _execute_reasoning_turn(automation: dict[str, Any]) -> str:
    from agent import api  # lazy import: the main api module mounts this router

    model_profile = automation.get("model_profile") or {}
    model = model_profile.get("model")
    if not model and model_profile.get("tier") == "fast":
        from agent.config import get_settings

        model = get_settings().fast_model
    reasoning_mode = _resolve_reasoning_mode(model_profile.get("reasoning_mode"))
    thread_id = _fresh_thread_id(automation)

    result = await api.agent.ainvoke(
        {"messages": [{"role": "user", "content": automation["instructions"]}]},
        config=api._thread_config(thread_id),
        model=model,
        reasoning_mode=reasoning_mode,
    )
    messages = result.get("messages", []) if isinstance(result, dict) else []
    return api._message_content(messages[-1] if messages else None) or "No response."


def _resolve_reasoning_mode(reasoning_mode: Any):
    if not reasoning_mode:
        return None
    from agent.llm.reasoning import resolve_reasoning_mode

    try:
        return resolve_reasoning_mode(reasoning_mode)
    except ValueError:
        return None


def _fresh_thread_id(automation: dict[str, Any]) -> str:
    destination = automation.get("destination") or {}
    if destination.get("kind") == "existing_chat":
        return str(destination.get("thread_id") or "")
    return f"automation-{uuid4().hex[:16]}"


def _deliver_result(automation: dict[str, Any], answer: str) -> None:
    """Land the run's result where the destination says.

    ``existing_chat`` appends a user/assistant turn to the pinned conversation;
    ``new_chat`` creates a fresh conversation in the UI feed (linked to the
    thread the turn ran in). Delivery problems never fail the run — the output
    stays visible in run history either way.
    """
    from agent import api  # lazy import: the main api module mounts this router

    destination = automation.get("destination") or {}
    thread_id = _fresh_thread_id(automation)
    user_text = automation["instructions"]
    try:
        if destination.get("kind") == "existing_chat":
            _append_thread_turn(api, thread_id, user_text, answer)
        else:
            _append_feed_conversation(api, automation, thread_id, user_text, answer)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AUTOMATIONS] delivery failed for %s: %s", automation["id"], exc)


def _append_thread_turn(api, thread_id: str, user_text: str, answer: str) -> None:
    conversations = api._read_ui_conversations()
    for conversation in conversations:
        if str(conversation.get("thread_id")) != thread_id:
            continue
        messages = conversation.setdefault("messages", [])
        messages.extend(
            [
                {"role": "user", "text": user_text, "id": f"automation-{uuid4().hex[:12]}"},
                {"role": "assistant", "text": answer, "id": f"automation-{uuid4().hex[:12]}"},
            ]
        )
        conversation["updated_at"] = api._conversation_timestamp()
        api._write_ui_conversations(conversations)
        return
    logger.warning("[AUTOMATIONS] pinned thread %s not found; result kept in run history", thread_id)


def _append_feed_conversation(
    api,
    automation: dict[str, Any],
    thread_id: str,
    user_text: str,
    answer: str,
) -> None:
    conversations = api._read_ui_conversations()
    record = {
        "id": thread_id,
        "thread_id": thread_id,
        "title": f"Automation: {automation.get('name', 'Scheduled run')}",
        "created": api._conversation_timestamp(),
        "pinned": False,
        "archived": False,
        "projectId": None,
        "messages": [
            {"role": "user", "text": user_text, "id": f"automation-{uuid4().hex[:12]}"},
            {"role": "assistant", "text": answer, "id": f"automation-{uuid4().hex[:12]}"},
        ],
        "updated_at": api._conversation_timestamp(),
        "organization": {},
    }
    conversations.insert(0, record)
    api._write_ui_conversations(conversations)
