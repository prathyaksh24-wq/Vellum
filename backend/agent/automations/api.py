"""Automation management API — replaces the ``/api/automations`` mock.

Backed by the user-owned ``AutomationStore`` (``data/automations.json``) and the
schedule parser. Run-now records a run and executes a reasoning turn through the
same agent path interactive chat uses (``agent.automations.runner``); the
scheduler wiring lands with the run-engine ticket.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.automations.store import AutomationStore
from agent.automations.validation import (
    parse_schedule_expression,
    validate_destination,
    validate_model_profile,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

router = APIRouter(prefix="/automations", tags=["automations"])

_AUTOMATIONS_STORE: AutomationStore | None = None

_MUTATION_HOOK: Any | None = None


def get_store() -> AutomationStore:
    global _AUTOMATIONS_STORE
    if _AUTOMATIONS_STORE is None:
        _AUTOMATIONS_STORE = AutomationStore(REPO_ROOT / "data")
    return _AUTOMATIONS_STORE


def set_store(store: AutomationStore | None) -> None:
    """Point the router at a different store (tests) or reset to default."""
    global _AUTOMATIONS_STORE
    _AUTOMATIONS_STORE = store


def set_mutation_hook(hook: Any | None) -> None:
    """Install a callback invoked after create/update/delete (scheduler sync)."""
    global _MUTATION_HOOK
    _MUTATION_HOOK = hook


def _notify_mutation(automation_id: str) -> None:
    hook = _MUTATION_HOOK
    if hook is None:
        return
    try:
        hook(automation_id)
    except Exception:  # noqa: BLE001 — the scheduler must never break the API
        pass


class AutomationDestination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["new_chat", "existing_chat"] = "new_chat"
    thread_id: str | None = None


class AutomationModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: Literal["primary", "fast"] | None = None
    model: str | None = None
    reasoning_mode: str | None = None


class AutomationPermission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_access: bool = False


class AutomationNotifications(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["all", "important", "failures", "none"] = "all"


class AutomationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""
    instructions: str = Field(min_length=1)
    schedule: str = Field(min_length=1)
    destination: AutomationDestination = Field(default_factory=AutomationDestination)
    project_id: str | None = None
    model_profile: AutomationModelProfile | None = None
    permission: AutomationPermission | None = None
    notifications: AutomationNotifications | None = None

    @field_validator("name", "instructions", "schedule")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("cannot be blank")
        return stripped

    @field_validator("description")
    @classmethod
    def _strip_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("project_id")
    @classmethod
    def _strip_project_id(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


class AutomationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    instructions: str | None = Field(default=None, min_length=1)
    schedule: str | None = None
    destination: AutomationDestination | None = None
    project_id: str | None = None
    model_profile: AutomationModelProfile | None = None
    permission: AutomationPermission | None = None
    notifications: AutomationNotifications | None = None
    state: Literal["active", "paused"] | None = None

    @field_validator("name", "description", "instructions", "schedule")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("project_id")
    @classmethod
    def _strip_optional_project_id(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


def _parsed_schedule(expression: str) -> dict[str, Any]:
    return parse_schedule_expression(expression)


def _validated_destination(destination: AutomationDestination) -> dict[str, Any]:
    return validate_destination(destination.kind, destination.thread_id)


def _validated_model_profile(profile: AutomationModelProfile | None) -> dict[str, Any]:
    if profile is None:
        return {}
    return validate_model_profile(
        tier=profile.tier,
        model=profile.model,
        reasoning_mode=profile.reasoning_mode,
    )


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def list_automations() -> dict[str, Any]:
    return {"automations": get_store().list()}


@router.get("/create-prompt")
async def automation_create_prompt() -> dict[str, Any]:
    """Explainer prompt used to prefill a new chat for chat-guided creation."""
    from agent.automations.prompts import CREATE_AUTOMATION_PROMPT

    return {"prompt": CREATE_AUTOMATION_PROMPT}


@router.post("")
async def create_automation(request: AutomationCreateRequest) -> dict[str, Any]:
    try:
        schedule = _parsed_schedule(request.schedule)
        destination = _validated_destination(request.destination)
        model_profile = _validated_model_profile(request.model_profile)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    record = get_store().create(
        name=request.name.strip(),
        description=request.description.strip(),
        instructions=request.instructions.strip(),
        schedule=schedule,
        destination=destination,
        project_id=request.project_id,
        model_profile=model_profile,
        permission=(
            request.permission.model_dump() if request.permission else {"full_access": False}
        ),
        notifications=(
            request.notifications.model_dump() if request.notifications else {"level": "all"}
        ),
    )
    _notify_mutation(record["id"])
    return {"automation": record}


@router.patch("/{automation_id}")
async def update_automation(automation_id: str, request: AutomationUpdateRequest) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    try:
        if request.name is not None:
            fields["name"] = request.name.strip()
        if request.description is not None:
            fields["description"] = request.description.strip()
        if request.instructions is not None:
            fields["instructions"] = request.instructions.strip()
        if request.schedule is not None:
            fields["schedule"] = _parsed_schedule(request.schedule)
        if request.destination is not None:
            fields["destination"] = _validated_destination(request.destination)
        if "project_id" in request.model_fields_set:
            fields["project_id"] = request.project_id
        if request.model_profile is not None:
            fields["model_profile"] = _validated_model_profile(request.model_profile)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    if request.permission is not None:
        fields["permission"] = request.permission.model_dump()
    if request.notifications is not None:
        fields["notifications"] = request.notifications.model_dump()
    if request.state is not None:
        fields["state"] = request.state
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    try:
        record = get_store().update(automation_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _notify_mutation(automation_id)
    return {"automation": record}


@router.post("/{automation_id}/run")
async def run_automation_now(automation_id: str) -> dict[str, Any]:
    store = get_store()
    try:
        automation = store.get(automation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from agent.automations.runner import run_automation_now as execute_run

    return {"run": await execute_run(automation, store)}


@router.delete("/{automation_id}")
async def delete_automation(automation_id: str) -> dict[str, Any]:
    store = get_store()
    try:
        record = store.get(automation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if record.get("builtin"):
        from agent.automations.builtins import reset_builtin

        reset_builtin(store, record)
        _notify_mutation(automation_id)
        return {"ok": True, "restored": True, "automation": store.get(automation_id)}
    store.remove(automation_id)
    _notify_mutation(automation_id)
    return {"ok": True}


@router.get("/{automation_id}/runs")
async def automation_runs(automation_id: str) -> dict[str, Any]:
    try:
        runs = get_store().runs(automation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"runs": runs}
