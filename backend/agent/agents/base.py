from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field


SpecialistStatus = Literal["answered", "needs_fetch", "stale", "blocked", "error"]
SourceKind = Literal["vault", "web", "api", "memory"]
Freshness = Literal["live", "recent", "stale", "historical"]
MemoryScope = Literal["sports", "x", "youtube", "memory", "mcp", "shared"]


class SpecialistSource(BaseModel):
    kind: SourceKind
    title: str
    path_or_url: str
    snippet: str = ""
    captured_at: str = ""
    freshness: Freshness = "historical"


class MemoryProposal(BaseModel):
    scope: MemoryScope
    claim: str
    evidence: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SpecialistResponse(BaseModel):
    agent: str
    status: SpecialistStatus
    summary: str
    analysis: str = ""
    sources: list[SpecialistSource] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    memory_proposals: list[MemoryProposal] = Field(default_factory=list)


class SpecialistAgent(Protocol):
    name: str

    def can_handle(self, query: str) -> bool:
        ...

    def answer(self, query: str) -> SpecialistResponse:
        ...
