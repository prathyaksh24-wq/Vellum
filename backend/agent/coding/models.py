from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_TENANT_ID = "local"
DEFAULT_PRINCIPAL_ID = "local-user"
DEFAULT_MAX_RUNTIME_SECONDS = 30 * 60
DEFAULT_MAX_PROVIDER_EVENTS = 10_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_trace_id() -> str:
    return f"trace_{uuid4().hex}"


class ProviderName(StrEnum):
    codex = "codex"
    claude = "claude"


class AccessMode(StrEnum):
    read_only = "read_only"
    workspace_write = "workspace_write"
    full_access = "full_access"
    ask_every_time = "ask_every_time"


@dataclass(frozen=True)
class ProviderHealth:
    provider: ProviderName
    available: bool
    configured: bool
    message: str


@dataclass(frozen=True)
class CodingTurnLimits:
    max_runtime_seconds: int = DEFAULT_MAX_RUNTIME_SECONDS
    max_provider_events: int = DEFAULT_MAX_PROVIDER_EVENTS

    def __post_init__(self) -> None:
        if self.max_runtime_seconds < 1:
            raise ValueError("max_runtime_seconds must be positive")
        if self.max_provider_events < 1:
            raise ValueError("max_provider_events must be positive")


@dataclass(frozen=True)
class CodingSessionCreate:
    provider: ProviderName
    cwd: str
    access_mode: AccessMode = AccessMode.read_only
    title: str = ""
    tenant_id: str = DEFAULT_TENANT_ID
    principal_id: str = DEFAULT_PRINCIPAL_ID

    def resolved_cwd(self) -> str:
        return str(Path(self.cwd).expanduser().resolve())


@dataclass(frozen=True)
class CodingSession:
    id: str
    provider: ProviderName
    cwd: str
    access_mode: AccessMode
    title: str
    status: str = "idle"
    provider_session_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    tenant_id: str = DEFAULT_TENANT_ID
    principal_id: str = DEFAULT_PRINCIPAL_ID
    workspace_generation: int = 1
    trace_id: str = field(default_factory=new_trace_id)


@dataclass(frozen=True)
class CodingTurn:
    id: str
    session_id: str
    prompt: str
    status: str
    started_at: str
    completed_at: str | None = None
    final_response: str = ""
    error: str = ""
    trace_id: str = field(default_factory=new_trace_id)
    max_runtime_seconds: int = DEFAULT_MAX_RUNTIME_SECONDS
    max_provider_events: int = DEFAULT_MAX_PROVIDER_EVENTS
    provider_event_count: int = 0


@dataclass(frozen=True)
class CodingEvent:
    id: str
    session_id: str
    turn_id: str | None
    provider: ProviderName
    type: str
    message: str
    payload: dict[str, Any]
    created_at: str
    trace_id: str = ""
    sequence: int = 0
