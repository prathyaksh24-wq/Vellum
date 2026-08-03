"""Run-now execution for automations.

Records the run, executes a full reasoning turn through the same agent path
interactive chat uses (model profile + reasoning mode applied), and writes the
outcome to run history. Failures are recorded with the error surfaced; they
never crash the API. Scheduler wiring, destination delivery, and permission
gating for unattended fires land with the run-engine ticket.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from agent.automations.store import AutomationStore


def _run_id() -> str:
    return f"run-{uuid4().hex[:16]}"


async def run_automation_now(
    automation: dict[str, Any],
    store: AutomationStore,
) -> dict[str, Any]:
    run = store.record_run(automation["id"], _run_id())
    try:
        answer = await _execute_reasoning_turn(automation)
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
