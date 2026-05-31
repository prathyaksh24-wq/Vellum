from __future__ import annotations

from dataclasses import dataclass

from agent.agents.base import MemoryProposal, SpecialistSource
from agent.master.registry import PupilRegistry


@dataclass(frozen=True)
class DelegationResult:
    task_id: str
    pupil: str
    status: str
    answer: str
    confidence: float
    sources: list[SpecialistSource]
    memory_proposals: list[MemoryProposal]


class DelegationManager:
    def __init__(self, registry: PupilRegistry) -> None:
        self.registry = registry

    def delegate(self, pupil_name: str, user_message: str, task_id: str) -> DelegationResult:
        pupil = self.registry.get(pupil_name)
        response = pupil.answer(user_message)
        return DelegationResult(
            task_id=task_id,
            pupil=response.agent,
            status=response.status,
            answer=response.summary,
            confidence=response.confidence,
            sources=response.sources,
            memory_proposals=response.memory_proposals,
        )
