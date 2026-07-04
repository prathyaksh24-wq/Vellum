from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    owner: str
    scope: str
    text: str
    confidence: float
    parent_id: str | None
    created_at: str


@dataclass(frozen=True)
class TaskRoom:
    id: str
    owner: str
    purpose: str
    participants: tuple[str, ...]
    status: str
    created_at: str


@dataclass(frozen=True)
class AgentMessage:
    id: str
    room_id: str
    sender: str
    recipient: str
    type: str
    claim: str
    evidence_refs: tuple[str, ...]
    confidence: float
    created_at: str
