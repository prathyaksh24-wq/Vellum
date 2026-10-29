"""Ephemeral context handoffs; durable memory continues through its existing owner."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class PacketEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str
    scope: str
    text: str = Field(max_length=1600)
    confidence: float = Field(ge=0, le=1)
    updated_at: str = ""
    sources: list[str] = Field(default_factory=list, max_length=6)


class AgentMemoryPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    source_agent: str
    recipient_agent: str
    purpose: str = Field(max_length=1000)
    thread_id: str
    user_id: str
    captured_at: datetime
    expires_at: datetime
    sensitivity: Literal["private_local"] = "private_local"
    authority: Literal["evidence_only"] = "evidence_only"
    items: list[PacketEvidence] = Field(default_factory=list, max_length=5)
