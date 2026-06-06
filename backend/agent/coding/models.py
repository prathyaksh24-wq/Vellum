from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


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
class CodingSessionCreate:
    provider: ProviderName
    cwd: str
    access_mode: AccessMode = AccessMode.read_only
    title: str = ""

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
