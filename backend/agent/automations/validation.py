"""Shared validation for automation payloads.

Used by both the HTTP router (mapping errors to 400 responses) and the agent's
``cronjob`` tool (mapping errors back into the conversation), so a schedule or
destination rejected by the API is rejected identically by the tool.
"""

from __future__ import annotations

from typing import Any

from agent.automations.schedules import ScheduleParseError, parse_schedule

NOTIFICATION_LEVELS = frozenset({"all", "important", "failures", "none"})


def parse_schedule_expression(expression: str) -> dict[str, Any]:
    """Parse a schedule expression into its canonical record."""
    return parse_schedule(expression).to_dict()


def validate_destination(
    kind: str = "new_chat",
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Validate a destination; ``existing_chat`` requires a pinned thread_id."""
    if kind not in ("new_chat", "existing_chat"):
        raise ValueError(f"invalid destination kind: {kind!r}")
    fields: dict[str, Any] = {"kind": kind}
    if thread_id is not None:
        fields["thread_id"] = thread_id
    if kind == "existing_chat" and not fields.get("thread_id"):
        raise ValueError("existing_chat destination requires a thread_id")
    return fields


def validate_model_profile(
    tier: str | None = None,
    model: str | None = None,
    reasoning_mode: str | None = None,
) -> dict[str, Any]:
    """Validate an optional model profile; unknown reasoning modes are rejected."""
    fields: dict[str, Any] = {}
    if tier is not None:
        if tier not in ("primary", "fast"):
            raise ValueError(f"invalid model tier: {tier!r}")
        fields["tier"] = tier
    if model:
        fields["model"] = model
    if reasoning_mode:
        from agent.llm.reasoning import resolve_reasoning_mode

        resolve_reasoning_mode(reasoning_mode)  # raises ValueError when unknown
        fields["reasoning_mode"] = reasoning_mode
    return fields


def validate_notifications_level(level: str | None = None) -> dict[str, str]:
    """Validate the notification preference shared by the API and cronjob tool."""
    value = (level or "all").strip().casefold()
    if value not in NOTIFICATION_LEVELS:
        raise ValueError(f"invalid notifications level: {level!r}")
    return {"level": value}
