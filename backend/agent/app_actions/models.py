"""Typed App Action requests, contexts, catalogs, and receipts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


ActionSource = Literal["nlp", "ui"]
ActionStatus = Literal[
    "applied",
    "confirmation_required",
    "unavailable",
    "failed",
    "undone",
]


class SurfacePresentation(BaseModel):
    visible: bool = True
    properties: dict[str, Any] = Field(default_factory=dict)


def _default_surfaces() -> dict[str, SurfacePresentation]:
    return {"sidebar": SurfacePresentation(visible=True)}


class WorkspaceLayoutSnapshot(BaseModel):
    version: int = Field(default=1, ge=1)
    revision: int = Field(default=0, ge=0)
    surfaces: dict[str, SurfacePresentation] = Field(default_factory=_default_surfaces)


class AppActionContext(BaseModel):
    source: ActionSource
    invocation_conversation_id: str = ""
    device_id: str = "local-device"
    workspace_layout: WorkspaceLayoutSnapshot = Field(default_factory=WorkspaceLayoutSnapshot)


class AppActionRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: f"action_{uuid4().hex}")
    action_id: str = Field(min_length=1)
    action_version: str = "1"
    arguments: dict[str, Any] = Field(default_factory=dict)


class ActionAuthorization(BaseModel):
    decision: Literal["allowed", "denied"]
    access_class: str
    confirmation_required: bool = False
    agent_name: str


class ActionTarget(BaseModel):
    kind: str
    id: str
    revision: int | None = None


class ActionUndo(BaseModel):
    token: str
    action_id: str
    arguments: dict[str, Any]
    expires_at: datetime
    target_revision: int


class ActionReceipt(BaseModel):
    receipt_id: str
    request_id: str
    action_id: str
    action_version: str
    source: ActionSource
    status: ActionStatus
    authorization: ActionAuthorization
    target: ActionTarget
    result: dict[str, Any] = Field(default_factory=dict)
    undo: ActionUndo | None = None
    message: str = ""
    error_code: str = ""
    audit_label: str = ""
    created_at: datetime


class AppActionDefinition(BaseModel):
    id: str
    version: str
    owner: str
    title: str
    description: str
    scope: str
    access_class: str
    confirmation_rule: str
    executor_location: str
    supports_undo: bool
    idempotent: bool
    argument_schema: dict[str, Any]
    result_schema: dict[str, Any]
    ui_reference: str
    audit_label: str


class AppActionCatalog(BaseModel):
    version: int = 1
    actions: list[AppActionDefinition]


class AppActionDispatchEnvelope(BaseModel):
    request: AppActionRequest
    context: AppActionContext


class AppActionUndoEnvelope(BaseModel):
    token: str = Field(min_length=1)
    context: AppActionContext
