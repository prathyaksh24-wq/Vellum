from __future__ import annotations

from collections.abc import Iterable

from agent.agents.base import SpecialistAgent, SpecialistResponse


class SpecialistOrchestrator:
    """Small parent-owned delegation helper.

    Mirrors Codex's useful subagent constraints for Vellum runtime agents:
    explicit parent delegation, depth cap, and one consolidated specialist
    response returned to Vellum.
    """

    def __init__(self, agents: Iterable[SpecialistAgent], max_depth: int = 1, max_concurrency: int = 1):
        self.agents = list(agents)
        self.max_depth = max_depth
        self.max_concurrency = max_concurrency

    def delegate(self, query: str, depth: int = 0) -> SpecialistResponse:
        if depth >= self.max_depth:
            return SpecialistResponse(
                agent="VellumAgent",
                status="blocked",
                summary="Specialist delegation depth limit reached.",
                confidence=1.0,
            )

        for agent in self.agents[: self.max_concurrency]:
            if agent.can_handle(query):
                return agent.answer(query)

        return SpecialistResponse(
            agent="VellumAgent",
            status="needs_fetch",
            summary="No specialist matched this query; Vellum should answer directly.",
            confidence=0.5,
        )
