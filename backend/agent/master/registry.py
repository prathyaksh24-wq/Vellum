from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agent.agents.base import SpecialistAgent
from agent.agents.memory_agent import MemoryAgent
from agent.agents.sports import SportsAgent
from agent.agents.x_agent import XAgent
from agent.agents.youtube import YoutubeAgent
from agent.tools.capabilities.registry import build_shared_tool_registry


class PupilRegistry:
    def __init__(self, pupils: Mapping[str, SpecialistAgent]) -> None:
        self._pupils = dict(pupils)

    @classmethod
    def default(cls, vault_root: Path) -> "PupilRegistry":
        root = Path(vault_root)
        tool_registry = build_shared_tool_registry(vault_root=root)
        pupils: list[SpecialistAgent] = [
            XAgent(vault_root=root, tool_registry=tool_registry),
            YoutubeAgent(vault_root=root, tool_registry=tool_registry),
            MemoryAgent(vault_root=root, tool_registry=tool_registry),
            SportsAgent(vault_root=root),
        ]
        return cls({pupil.name: pupil for pupil in pupils})

    def get(self, name: str) -> SpecialistAgent:
        return self._pupils[name]

    def names(self) -> list[str]:
        return sorted(self._pupils)

    def match(self, query: str) -> SpecialistAgent | None:
        for pupil in self._pupils.values():
            if pupil.can_handle(query):
                return pupil
        return None
