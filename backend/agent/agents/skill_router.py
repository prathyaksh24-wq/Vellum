from __future__ import annotations

from dataclasses import dataclass

from agent.memory.skills import SkillStore


@dataclass(frozen=True)
class SkillRoute:
    agent_name: str
    skill_id: str


class SkillRouteResolver:
    def __init__(self, skill_store: SkillStore | None = None):
        self.skill_store = skill_store or SkillStore()

    def resolve(self, query: str) -> SkillRoute | None:
        for skill in self.skill_store.matching_skills(query):
            agent_name = skill.get("route_to_agent")
            if isinstance(agent_name, str) and agent_name:
                return SkillRoute(agent_name=agent_name, skill_id=str(skill.get("id", "")))
        return None
