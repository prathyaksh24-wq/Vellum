from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.agents.sports import SportsAgent
from agent.agents.x_agent import XAgent
from agent.agents.youtube import YoutubeAgent


@dataclass(frozen=True)
class RouteDecision:
    agent_name: str
    should_delegate: bool
    reason: str


class SpecialistRouter:
    def __init__(self, vault_root: Path) -> None:
        self.vault_root = Path(vault_root)
        self._specialists = (
            SportsAgent(vault_root=self.vault_root),
            XAgent(vault_root=self.vault_root),
            YoutubeAgent(vault_root=self.vault_root),
        )

    def route(self, query: str) -> RouteDecision:
        for agent in self._specialists:
            if agent.can_handle(query):
                return RouteDecision(
                    agent_name=agent.name,
                    should_delegate=True,
                    reason=f"{agent.name} matched the query.",
                )
        return RouteDecision(
            agent_name="VellumAgent",
            should_delegate=False,
            reason="No specialist matched; keep the request with the main Vellum agent.",
        )
