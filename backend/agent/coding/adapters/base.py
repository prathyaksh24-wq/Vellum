from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from agent.coding.models import (
    CodingEvent,
    CodingSession,
    CodingSessionCreate,
    ProviderCapabilities,
    ProviderHealth,
    ProviderName,
)


class CodingAdapterError(RuntimeError):
    pass


class CodingProviderAdapter(Protocol):
    provider: ProviderName

    def health(self) -> ProviderHealth:
        ...

    def capabilities(self) -> ProviderCapabilities:
        ...

    async def start_session(self, request: CodingSessionCreate) -> str | None:
        ...

    def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        ...

    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        ...
