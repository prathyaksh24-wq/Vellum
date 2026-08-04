"""Cronjob action tool — chat-guided automation management.

A single Hermes-style action tool (like ``skill_manage``): the reasoning agent
uses ``cronjob`` to create, list, update, pause/resume, run-now, or remove
automations from any conversation. It talks to the same store the HTTP router
uses, applies the identical validation (``agent.automations.validation``), and
surfaces every validation error back into the conversation as JSON.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain_core.tools import tool

from agent.automations import api as automations_api
from agent.automations.validation import (
    parse_schedule_expression,
    validate_destination,
    validate_model_profile,
    validate_notifications_level,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _store() -> Any:
    return automations_api.get_store()


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    runs = record.get("run_history") or []
    last = runs[-1] if runs else None
    return {
        "id": record["id"],
        "name": record["name"],
        "description": record.get("description") or "",
        "instructions": record.get("instructions"),
        "schedule": record.get("schedule"),
        "destination": record.get("destination"),
        "project_id": record.get("project_id"),
        "model_profile": record.get("model_profile") or {},
        "permission": record.get("permission") or {},
        "notifications": record.get("notifications") or {"level": "all"},
        "state": record.get("state"),
        "builtin": bool(record.get("builtin")),
        "run_count": len(runs),
        "last_run": last,
    }


def _lookup(automation_id: str) -> dict[str, Any]:
    return _store().get(automation_id)


def _create(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    instructions = str(payload.get("instructions") or "").strip()
    description = str(payload.get("description") or "").strip()
    schedule_expression = str(payload.get("schedule") or "").strip()
    if not name:
        raise ValueError("name is required")
    if not instructions:
        raise ValueError("instructions are required")
    if not schedule_expression:
        raise ValueError("schedule is required")
    record = _store().create(
        name=name,
        description=description,
        instructions=instructions,
        schedule=parse_schedule_expression(schedule_expression),
        destination=validate_destination(
            str(payload.get("destination") or "new_chat"),
            str(payload.get("thread_id") or "") or None,
        ),
        model_profile=validate_model_profile(
            tier=str(payload.get("tier") or "") or None,
            model=str(payload.get("model") or "") or None,
            reasoning_mode=str(payload.get("reasoning_mode") or "") or None,
        ),
        permission={"full_access": bool(payload.get("full_access"))},
        project_id=str(payload.get("project_id") or "").strip() or None,
        notifications=validate_notifications_level(str(payload.get("notifications") or "all")),
    )
    automations_api._notify_mutation(record["id"])
    return {"ok": True, "automation": _record_summary(record)}


def _list() -> dict[str, Any]:
    return {
        "ok": True,
        "automations": [_record_summary(record) for record in _store().list()],
    }


def _update(payload: dict[str, Any]) -> dict[str, Any]:
    automation_id = str(payload.get("automation_id") or "")
    record = _lookup(automation_id)
    fields: dict[str, Any] = {}
    name = str(payload.get("name") or "").strip()
    if name:
        fields["name"] = name
    instructions = str(payload.get("instructions") or "").strip()
    if instructions:
        fields["instructions"] = instructions
    if "description" in payload:
        fields["description"] = str(payload.get("description") or "").strip()
    schedule_expression = str(payload.get("schedule") or "").strip()
    if schedule_expression:
        fields["schedule"] = parse_schedule_expression(schedule_expression)
    destination = str(payload.get("destination") or "")
    if destination:
        fields["destination"] = validate_destination(destination, str(payload.get("thread_id") or "") or None)
    if payload.get("tier") or payload.get("model") or payload.get("reasoning_mode"):
        fields["model_profile"] = validate_model_profile(
            tier=str(payload.get("tier") or "") or None,
            model=str(payload.get("model") or "") or None,
            reasoning_mode=str(payload.get("reasoning_mode") or "") or None,
        )
    if payload.get("full_access") is not None:
        fields["permission"] = {"full_access": bool(payload["full_access"])}
    if "project_id" in payload:
        fields["project_id"] = str(payload.get("project_id") or "").strip() or None
    if payload.get("notifications"):
        fields["notifications"] = validate_notifications_level(str(payload["notifications"]))
    if not fields:
        raise ValueError("no fields to update; pass at least one of name/instructions/schedule/destination/model/full_access")
    updated = _store().update(automation_id, **fields)
    automations_api._notify_mutation(automation_id)
    return {"ok": True, "automation": _record_summary(updated)}


def _set_state(automation_id: str, state: str) -> dict[str, Any]:
    record = _lookup(automation_id)
    updated = _store().update(record["id"], state=state)
    automations_api._notify_mutation(record["id"])
    return {"ok": True, "automation": _record_summary(updated)}


def _remove(automation_id: str) -> dict[str, Any]:
    record = _lookup(automation_id)
    if record.get("builtin"):
        from agent.automations.builtins import reset_builtin

        restored = reset_builtin(_store(), record)
        automations_api._notify_mutation(record["id"])
        return {
            "ok": True,
            "restored": True,
            "message": "built-in automation cannot be removed; restored to defaults",
            "automation": _record_summary(restored),
        }
    _store().remove(record["id"])
    automations_api._notify_mutation(record["id"])
    return {"ok": True, "removed": record["id"]}


def _run_now(automation_id: str) -> dict[str, Any]:
    record = _lookup(automation_id)

    from agent.automations.runner import run_automation_now

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        run = asyncio.run(run_automation_now(record, _store()))
        return {"ok": True, "run": run}
    loop.create_task(run_automation_now(record, _store()))
    return {
        "ok": True,
        "queued": True,
        "automation_id": record["id"],
        "message": "run started in the background",
    }


@tool
def cronjob(
    action: str,
    automation_id: str = "",
    name: str = "",
    instructions: str = "",
    description: str = "",
    schedule: str = "",
    destination: str = "new_chat",
    thread_id: str = "",
    model: str = "",
    tier: str = "",
    reasoning_mode: str = "",
    full_access: bool | None = None,
    project_id: str = "",
    notifications: str = "",
) -> str:
    """Create, list, update, pause, resume, run-now, or remove automations (scheduled reasoning tasks) from this chat.

    Actions:
    - create — needs name, instructions, and schedule; optional destination
      ('new_chat' or 'existing_chat' with thread_id), model, tier ('primary' or
      'fast'), reasoning_mode, and full_access.
    - list — returns all automations with their schedule, destination, state, and last run.
    - update — needs automation_id plus any fields to change (name, instructions,
      schedule, destination, thread_id, model, tier, reasoning_mode, full_access).
    - pause / resume — needs automation_id.
    - run — needs automation_id; executes the automation now (in the background).
    - remove — needs automation_id; built-in automations are restored to their defaults instead of deleted.

    Schedule formats: '30m' (one-shot delay), 'every 2h' (recurring interval),
    '0 9 * * *' (5-field cron, UTC), or an ISO timestamp like
    '2026-08-03T09:00:00Z'. Confirm the full plan with the user before creating
    or removing. Validation errors are returned in the result, never thrown."""
    normalized = action.strip().casefold().replace("-", "_")
    payload: dict[str, Any] = {
        "automation_id": automation_id,
        "name": name,
        "instructions": instructions,
        "description": description,
        "schedule": schedule,
        "destination": destination,
        "thread_id": thread_id,
        "model": model,
        "tier": tier,
        "reasoning_mode": reasoning_mode,
        "full_access": full_access,
        "project_id": project_id,
        "notifications": notifications,
    }
    try:
        if normalized in ("create", "add"):
            return _json(_create(payload))
        if normalized in ("list", "ls", "status"):
            return _json(_list())
        if normalized == "update":
            return _json(_update(payload))
        if normalized in ("pause", "pause_automation"):
            return _json(_set_state(payload["automation_id"], "paused"))
        if normalized in ("resume", "unpause", "resume_automation"):
            return _json(_set_state(payload["automation_id"], "active"))
        if normalized in ("run", "run_now", "trigger"):
            return _json(_run_now(payload["automation_id"]))
        if normalized in ("remove", "delete", "remove_automation"):
            return _json(_remove(payload["automation_id"]))
        return _json(
            {
                "ok": False,
                "error": (
                    f"Unsupported cronjob action: {action!r}. "
                    "Supported: create, list, update, pause, resume, run, remove."
                ),
            }
        )
    except ValueError as exc:
        return _json({"ok": False, "error": str(exc)})
