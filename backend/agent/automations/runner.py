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
    conversation_id: str | None = None
    destination = (automation.get("destination") or {}).get("kind")
    answer = ""
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
                from agent.automations.builtins import describe_builtin_result
                # Counts only: history results carry account identifiers that stay out of chats.
                details = describe_builtin_result("YouTube history refresh", {
                    k: v for k, v in result.items()
                    if k not in {"status", "records"} and isinstance(v, (int, float)) and not isinstance(v, bool)})
                if details and not details.endswith("finished."):
                    answer += "\n" + details
            conversation_id = _deliver_builtin_report(automation, store, answer, run["id"])
            return store.finish_run(automation['id'], run['id'], status='complete', output=answer,
                                    conversation_id=conversation_id, message_id=run["id"] if conversation_id else None)
        if automation.get("builtin"):
            from agent.automations.builtins import describe_builtin_result, run_builtin
            result = await run_builtin(automation, raise_errors=True)
            report = describe_builtin_result(str(automation.get("name") or "Task"), result)
            conversation_id = _deliver_builtin_report(automation, store, report, run["id"])
            return store.finish_run(automation["id"], run["id"], status="complete", output=report,
                                    conversation_id=conversation_id,
                                    message_id=run["id"] if conversation_id else None)
        execution = {**automation, "_execution_thread_id": _fresh_thread_id(automation)}
        answer = await _execute_reasoning_turn(execution)
        if not str(answer or "").strip() or answer == "No response.":
            raise RuntimeError("The model returned no answer for this run.")
        destination = (automation.get("destination") or {}).get("kind")
        if destination != "notification":
            conversation_id = _deliver_result(execution, answer, run["id"])
        finished = store.finish_run(automation["id"], run["id"], status="complete", output=answer,
                                    conversation_id=conversation_id, message_id=run["id"] if conversation_id else None)
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        conversation_id = _deliver_failure(automation, error, run["id"])
        finished = store.finish_run(automation["id"], run["id"], status="failed", error=error,
                                    conversation_id=conversation_id,
                                    message_id=run["id"] if conversation_id else None)
    try:
        if finished["status"] == "failed":
            store.deliver_notification(automation["id"], run["id"], f"The task failed: {finished.get('error') or 'unknown error'}"[:500],
                                       failed=True, conversation_id=conversation_id or "")
        elif destination == "notification":
            store.deliver_notification(automation["id"], run["id"], answer)
        elif (automation.get("notifications") or {}).get("level", "all") == "all":
            store.deliver_notification(automation["id"], run["id"], _preview(answer), conversation_id=conversation_id or "")
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
    if not model:
        # Use the model chat uses (the picker's active, available model) rather than the
        # configured primary, which may name a model that is not installed.
        import asyncio

        model = await asyncio.to_thread(active_chat_model)
    reasoning_mode = _resolve_reasoning_mode(model_profile.get("reasoning_mode"))
    thread_id = automation.get("_execution_thread_id") or _fresh_thread_id(automation)

    result = await api.agent.ainvoke(
        {"messages": [{"role": "user", "content": run_message(automation)}]},
        config=api._thread_config(thread_id),
        model=model,
        reasoning_mode=reasoning_mode,
    )
    messages = result.get("messages", []) if isinstance(result, dict) else []
    return api._message_content(messages[-1] if messages else None) or "No response."


RUN_NOTE = (
    "[Automation run of the task \"{name}\". Vellum already runs this task on its schedule, so this message "
    "is one occurrence of it: wording like \"every day\" or \"each week\" describes the schedule, which is "
    "handled. Do not set up, confirm or discuss scheduling or reminders, and do not create another automation; "
    "produce this occurrence's result now (for example, today's item). This is not a conversation: nobody will "
    "answer questions during this run. Do the task completely right now and write the finished result for the "
    "user. Never ask "
    "whether to start, which option they prefer, or for confirmation; when something is ambiguous, pick the "
    "most sensible choice, do it, and mention the choice in one short line.{approval}]\n\n"
)
ASK_FIRST_APPROVAL = (
    " Do not send, post, buy, book, delete, or change settings or accounts, and do not take any other step "
    "that needs the user's approval: list those as suggested next steps in your result instead."
)
# Kept for callers that still import it.
ASK_FIRST_NOTE = RUN_NOTE.replace("{approval}", ASK_FIRST_APPROVAL)


def active_chat_model() -> str | None:
    """The active model the chat picker shows, when it is available right now."""
    try:
        from agent.llm.providers import get_provider_registry

        active = get_provider_registry().current_available_model()
    except Exception as exc:  # noqa: BLE001 — fall back to the agent's default route
        logger.warning("[AUTOMATIONS] could not resolve the active chat model: %s", exc)
        return None
    return active.id if active is not None else None


def run_message(automation: dict[str, Any]) -> str:
    """The user turn a run executes.

    Every run (scheduled or Run now) is told to finish the task without asking
    questions; without the full-access opt-in it also may not take steps that
    need the user's approval.
    """
    instructions = str(automation.get("instructions") or "")
    full_access = bool((automation.get("permission") or {}).get("full_access"))
    note = RUN_NOTE.format(name=automation.get("name") or "Scheduled task",
                           approval="" if full_access else ASK_FIRST_APPROVAL)
    return note + instructions


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


def task_conversation_id(automation_id: str) -> str:
    """The one chat each automation owns; the Scheduled page opens the same id."""
    return f"scheduled-task-{automation_id}"


def _preview(text: str) -> str:
    line = " ".join(str(text or "").split())
    return line[:280] + ("…" if len(line) > 280 else "")


def _run_heading(automation: dict[str, Any]) -> str:
    from datetime import datetime

    stamp = datetime.now().astimezone().strftime("%b %d, %H:%M")
    return f"**{automation.get('name') or 'Scheduled task'}** · run {stamp}"


def _append_to_task_chat(automation: dict[str, Any], text: str, delivery_id: str) -> str | None:
    """Append a run's message to the automation's own chat, creating it once."""
    from agent import api  # lazy import: the main api module mounts this router
    from agent.conversations.lifecycle import ConversationLifecycle

    chat_id = task_conversation_id(automation["id"])
    lifecycle = ConversationLifecycle(path=api._UI_CONVERSATIONS_PATH)
    try:
        exists = any(str(chat.get("id")) == chat_id for chat in lifecycle.list())
        lifecycle.deliver_automation(
            delivery_id=delivery_id, text=text, name=str(automation.get("name") or "Scheduled task"),
            new_chat_id=chat_id, project_id=automation.get("project_id"),
            instructions="" if exists or automation.get("builtin") else str(automation.get("instructions") or ""),
        )
        return chat_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AUTOMATIONS] delivery failed for %s: %s", automation["id"], exc)
        return None


def _run_stamp() -> str:
    from datetime import datetime

    return datetime.now().astimezone().strftime("%b %d, %H:%M")


def _new_run_chat(automation: dict[str, Any], text: str, run_id: str, chat_id: str = "") -> str | None:
    """A run's own chat, listed under its task in the Scheduled sidebar (never the main one)."""
    from agent import api  # lazy import: the main api module mounts this router
    from agent.conversations.lifecycle import ConversationLifecycle

    chat_id = chat_id or f"automation-{uuid4().hex[:16]}"
    try:
        ConversationLifecycle(path=api._UI_CONVERSATIONS_PATH).deliver_automation(
            delivery_id=run_id, text=text, name=f"{automation.get('name') or 'Scheduled task'} · {_run_stamp()}",
            new_chat_id=chat_id, project_id=automation.get("project_id"),
            instructions=str(automation.get("instructions") or ""),
        )
        return chat_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AUTOMATIONS] delivery failed for %s: %s", automation["id"], exc)
        return None


def _deliver_result(automation: dict[str, Any], answer: str, run_id: str) -> str | None:
    """Land the run's result where the task's destination setting says.

    ``new_chat``: every run gets a chat of its own (the thread it ran in), shown
    nested under the task in the Scheduled sidebar. ``existing_chat``: the result
    is appended to the conversation the task was pinned to. Delivery problems
    never fail the run — the output stays visible in run history either way.
    """
    from agent import api  # lazy import: the main api module mounts this router
    from agent.conversations.lifecycle import ConversationLifecycle

    destination = automation.get("destination") or {}
    thread_id = automation["_execution_thread_id"]
    if destination.get("kind") != "existing_chat":
        return _new_run_chat(automation, answer, run_id, chat_id=thread_id)
    lifecycle = ConversationLifecycle(path=api._UI_CONVERSATIONS_PATH)
    try:
        lifecycle.deliver_automation(
            delivery_id=run_id, text=answer, name=str(automation["name"]),
            thread_id=thread_id, project_id=automation.get("project_id"), instructions=automation["instructions"],
        )
        return next((str(chat["id"]) for chat in lifecycle.list() if chat.get("thread_id") == thread_id), None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AUTOMATIONS] delivery failed for %s: %s", automation["id"], exc)
        return None


def _deliver_failure(automation: dict[str, Any], error: str, run_id: str) -> str | None:
    """A failed run is visible where its result would have been, so nothing fails silently."""
    kind = (automation.get("destination") or {}).get("kind")
    if kind in {"notification", "existing_chat"}:
        return None  # the notification and Previous runs carry the error
    if automation.get("builtin"):
        if automation.get("_unattended"):
            # Frequent background jobs: a streak of the same failure must not flood the chat.
            last = next((run for run in reversed(automation.get("run_history") or [])
                         if run.get("status") in {"complete", "failed"}), None)
            if last is not None and last.get("status") == "failed" and last.get("error") == error:
                return None
        return _append_to_task_chat(automation, f"{_run_heading(automation)}\n\nThis run failed: {error}", run_id)
    return _new_run_chat(automation, f"This run failed: {error}", run_id)


def _deliver_builtin_report(automation: dict[str, Any], store: AutomationStore, report: str, run_id: str) -> str | None:
    """Show what a built-in job did in its chat; scheduled runs that changed nothing are skipped."""
    try:
        history = store.get(automation["id"]).get("run_history") or []
    except ValueError:
        history = []
    previous = next((run.get("output") for run in reversed(history)
                     if run.get("id") != run_id and run.get("status") == "complete" and run.get("output")), None)
    if automation.get("_unattended") and previous == report:
        return None
    return _append_to_task_chat(automation, f"{_run_heading(automation)}\n\n{report}", run_id)
