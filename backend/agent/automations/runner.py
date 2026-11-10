"""Run-now execution for automations.

Records the run, executes a full reasoning turn through the same agent path
interactive chat uses (model profile + reasoning mode applied), delivers the
result to the destination (append into the pinned thread for ``existing_chat``,
a new conversation in the UI feed for ``new_chat``, or a persistent in-app ping
for ``notification``), and writes the outcome to
run history. Failures are recorded with the error surfaced; they never crash
the API. Scheduled fires and the skip-if-busy / full-access gates live in
``agent.automations.scheduler``.
"""

from __future__ import annotations

import logging
import re
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
        if automation.get("builtin") and automation.get("builtin_key") == "youtube_creator_tracking":
            import asyncio
            from agent.plugins.youtube_creator_tracking import YouTubeCreatorTracking
            result = await asyncio.to_thread(YouTubeCreatorTracking().refresh,
                deliver=lambda delivery_id, text: _deliver_creator_upload(automation, delivery_id, text, store))
            return store.finish_run(automation["id"], run["id"], status="complete",
                output=f"Creator tracking: {result['status']}. {result['requests']} feed requests; {result.get('fallback_checks', 0)} API fallback checks; {result['delivered']} delivered uploads.")
        if automation.get('builtin') and automation.get('builtin_key') == 'youtube_browser_history':
            from agent.automations.builtins import run_builtin
            result = await run_builtin(automation, raise_errors=True)
            status = result['status']
            if status == 'browser_busy':
                answer = 'History refresh deferred while another browser operation or refresh is running. Saved history is unchanged.'
            else:
                answer = ('YouTube history refreshed.' if status == 'ready' else 'YouTube history checked; the current page is empty.')
                answer += f" {int(result.get('records') or 0)} saved video/day entries."
            return store.finish_run(automation['id'], run['id'], status='complete', output=answer)
        if automation.get("builtin"):
            from agent.automations.builtins import run_builtin
            await run_builtin(automation, raise_errors=True)
            return store.finish_run(automation["id"], run["id"], status="complete")
        execution = {**automation, "_execution_thread_id": _fresh_thread_id(automation)}
        answer = await _execute_reasoning_turn(execution)
        destination = (automation.get("destination") or {}).get("kind")
        conversation_id = None
        if destination != "notification":
            conversation_id = _deliver_result(execution, answer, run["id"])
        finished = store.finish_run(automation["id"], run["id"], status="complete", output=answer,
                                    conversation_id=conversation_id, message_id=run["id"] if conversation_id else None)
    except Exception as exc:
        finished = store.finish_run(automation["id"], run["id"], status="failed", error=str(exc))
    try:
        if finished["status"] == "failed":
            store.deliver_notification(automation["id"], run["id"], "The task failed. See Previous runs for details.", failed=True)
        elif destination == "notification":
            store.deliver_notification(automation["id"], run["id"], answer)
        elif (automation.get("notifications") or {}).get("level", "all") == "all":
            store.deliver_notification(automation["id"], run["id"], "The task completed. See Previous runs for the result.")
    except (OSError, ValueError) as exc:
        logger.warning("[AUTOMATIONS] Notification delivery failed for %s: %s", automation["id"], exc)
    return finished


async def _execute_reasoning_turn(automation: dict[str, Any]) -> str:
    from agent import api  # lazy import: the main api module mounts this router

    model_profile = automation.get("model_profile") or {}
    model = model_profile.get("model")
    if not model and model_profile.get("tier") == "fast":
        from agent.config import get_settings

        model = get_settings().fast_model
    reasoning_mode = _resolve_reasoning_mode(model_profile.get("reasoning_mode"))
    thread_id = automation.get("_execution_thread_id") or _fresh_thread_id(automation)

    result = await api.agent.ainvoke(
        {"messages": [{"role": "user", "content": automation["instructions"]}]},
        config=api._thread_config(thread_id),
        model=model,
        reasoning_mode=reasoning_mode,
    )
    messages = result.get("messages", []) if isinstance(result, dict) else []
    return api._message_content(messages[-1] if messages else None) or "No response."


def _deliver_creator_upload(automation, delivery_id, text, store):
    if (automation.get("destination") or {}).get("kind") == "notification":
        link = re.search(r"https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}(?![A-Za-z0-9_-])", text)
        return store.deliver_notification(automation["id"], delivery_id, text,
            title="New YouTube upload", url=link.group(0) if link else "")
    from agent import api
    from agent.conversations.lifecycle import ConversationLifecycle
    destination = automation.get("destination") or {}
    return ConversationLifecycle(path=api._UI_CONVERSATIONS_PATH).deliver_automation(
        delivery_id=delivery_id, text=text, name="YouTube creator upload",
        thread_id=str(destination.get("thread_id") or "") if destination.get("kind") == "existing_chat" else "",
        project_id=automation.get("project_id"))


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


def _deliver_result(automation: dict[str, Any], answer: str, run_id: str) -> str | None:
    """Land the run's result where the destination says.

    ``existing_chat`` appends a user/assistant turn to the pinned conversation;
    ``new_chat`` creates a fresh conversation in the UI feed (linked to the
    thread the turn ran in). Delivery problems never fail the run — the output
    stays visible in run history either way.
    """
    from agent import api  # lazy import: the main api module mounts this router
    from agent.conversations.lifecycle import ConversationLifecycle

    destination = automation.get("destination") or {}
    thread_id = automation["_execution_thread_id"]
    existing = destination.get("kind") == "existing_chat"
    lifecycle = ConversationLifecycle(path=api._UI_CONVERSATIONS_PATH)
    try:
        lifecycle.deliver_automation(
            delivery_id=run_id, text=answer, name=f"Automation: {automation['name']}",
            thread_id=thread_id if existing else "", new_chat_id=thread_id if not existing else "",
            project_id=automation.get("project_id"), instructions=automation["instructions"],
        )
        if not existing:
            return thread_id
        return next((str(chat["id"]) for chat in lifecycle.list() if chat.get("thread_id") == thread_id), None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AUTOMATIONS] delivery failed for %s: %s", automation["id"], exc)
        return None
