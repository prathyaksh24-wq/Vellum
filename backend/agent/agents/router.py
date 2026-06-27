from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.agents.skill_router import SkillRouteResolver
from agent.agents.sports import SportsAgent
from agent.agents.x_agent import XAgent
from agent.agents.youtube import YoutubeAgent


@dataclass(frozen=True)
class RouteDecision:
    agent_name: str
    should_delegate: bool
    reason: str


class SpecialistRouter:
    def __init__(self, vault_root: Path, skill_route_resolver: SkillRouteResolver | None = None) -> None:
        self.vault_root = Path(vault_root)
        self._specialists = (
            XAgent(vault_root=self.vault_root),
            YoutubeAgent(vault_root=self.vault_root),
            SportsAgent(vault_root=self.vault_root),
        )
        self.skill_route_resolver = skill_route_resolver or SkillRouteResolver()

    def route(self, query: str) -> RouteDecision:
        skill_route = self.skill_route_resolver.resolve(query)
        if skill_route is not None:
            return RouteDecision(
                agent_name=skill_route.agent_name,
                should_delegate=True,
                reason=f"matched routing skill {skill_route.skill_id}",
            )
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
