"""Public contracts for run traces and per-conversation context windows.

Both are metadata only: event types, tool/agent names, timings and token counts.
Prompt text, answers, tool arguments and source contents never cross this boundary."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ContextWindowShape(BaseModel):
    response_id: str
    thread_id: str
    ts: str
    context_window: int
    input_used: int
    input_limit: int
    output_reserved: int
    safety_margin: int
    layers: dict[str, int] = Field(default_factory=dict)
    compacted: bool = False
    removed_messages: int = 0


class ContextFillPoint(BaseModel):
    response_id: str
    ts: str
    input_used: int
    input_limit: int
    compacted: bool


class ThreadContext(BaseModel):
    thread_id: str
    latest: ContextWindowShape | None = None
    history: list[ContextFillPoint] = Field(default_factory=list)
    compactions: int = 0


class TraceSpan(BaseModel):
    id: str
    parent: str | None = None
    kind: Literal["context", "runtime", "thinking", "agent", "tool", "source", "answer", "compaction", "memory", "error"]
    name: str = ""
    label: str = ""
    start_ms: float
    end_ms: float
    status: str
    count: int = 1


class TraceRun(BaseModel):
    response_id: str
    thread_id: str
    status: str
    started_at: str
    completed_at: str | None = None
    event_count: int = 0
    tool_count: int = 0
    source_count: int = 0


class TraceStats(BaseModel):
    events: int = 0
    tool_calls: int = 0
    agents: int = 0
    sources: int = 0
    errors: int = 0


class RunTrace(BaseModel):
    run: TraceRun
    duration_ms: float
    origin_at_ms: float = 0
    precise: bool
    spans: list[TraceSpan]
    stats: TraceStats
    context: ContextWindowShape | None = None
