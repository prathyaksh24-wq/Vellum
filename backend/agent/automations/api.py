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

from agent.automations.schedules import ScheduleParseError, parse_schedule
from agent.automations.store import AutomationStore

REPO_ROOT = Path(__file__).resolve().parents[3]

router = APIRouter(prefix="/automations", tags=["automations"])

_AUTOMATIONS_STORE: AutomationStore | None = None


def get_store() -> AutomationStore:
    global _AUTOMATIONS_STORE
    if _AUTOMATIONS_STORE is None:
        _AUTOMATIONS_STORE = AutomationStore(REPO_ROOT / "data")
    return _AUTOMATIONS_STORE


def set_store(store: AutomationStore | None) -> None:
    """Point the router at a different store (tests) or reset to default."""
    global _AUTOMATIONS_STORE
    _AUTOMATIONS_STORE = store


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


class AutomationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    schedule: str = Field(min_length=1)
    destination: AutomationDestination = Field(default_factory=AutomationDestination)
    model_profile: AutomationModelProfile | None = None
    permission: AutomationPermission | None = None

    @field_validator("name", "instructions", "schedule")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("cannot be blank")
        return stripped


class AutomationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    instructions: str | None = Field(default=None, min_length=1)
    schedule: str | None = None
    destination: AutomationDestination | None = None
    model_profile: AutomationModelProfile | None = None
    permission: AutomationPermission | None = None
    state: Literal["active", "paused"] | None = None


def _parsed_schedule(expression: str) -> dict[str, Any]:
    try:
        return parse_schedule(expression).to_dict()
    except ScheduleParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validated_destination(destination: AutomationDestination) -> dict[str, Any]:
    fields = destination.model_dump(exclude_none=True)
    if fields.get("kind") == "existing_chat" and not fields.get("thread_id"):
        raise HTTPException(
            status_code=400,
            detail="existing_chat destination requires a thread_id",
        )
    return fields


def _validated_model_profile(profile: AutomationModelProfile | None) -> dict[str, Any]:
    if profile is None:
        return {}
    fields = profile.model_dump(exclude_none=True)
    if fields.get("reasoning_mode"):
        from agent.llm.reasoning import resolve_reasoning_mode

        try:
            resolve_reasoning_mode(fields["reasoning_mode"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return fields


@router.get("")
async def list_automations() -> dict[str, Any]:
    return {"automations": get_store().list()}


@router.post("")
async def create_automation(request: AutomationCreateRequest) -> dict[str, Any]:
    record = get_store().create(
        name=request.name.strip(),
        instructions=request.instructions.strip(),
        schedule=_parsed_schedule(request.schedule),
        destination=_validated_destination(request.destination),
        model_profile=_validated_model_profile(request.model_profile),
        permission=(
            request.permission.model_dump() if request.permission else {"full_access": False}
        ),
    )
    return {"automation": record}


@router.patch("/{automation_id}")
async def update_automation(automation_id: str, request: AutomationUpdateRequest) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if request.name is not None:
        fields["name"] = request.name.strip()
    if request.instructions is not None:
        fields["instructions"] = request.instructions.strip()
    if request.schedule is not None:
        fields["schedule"] = _parsed_schedule(request.schedule)
    if request.destination is not None:
        fields["destination"] = _validated_destination(request.destination)
    if request.model_profile is not None:
        fields["model_profile"] = _validated_model_profile(request.model_profile)
    if request.permission is not None:
        fields["permission"] = request.permission.model_dump()
    if request.state is not None:
        fields["state"] = request.state
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    try:
        record = get_store().update(automation_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
    try:
        get_store().remove(automation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/{automation_id}/runs")
async def automation_runs(automation_id: str) -> dict[str, Any]:
    try:
        runs = get_store().runs(automation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"runs": runs}
