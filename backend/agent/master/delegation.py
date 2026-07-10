from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from agent.agents.base import MemoryProposal, SpecialistSource
from agent.master.registry import PupilRegistry

if TYPE_CHECKING:
    from agent.master.runtime import DelegationRuntime


logger = logging.getLogger(__name__)


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
    def __init__(self, registry: PupilRegistry, runtime: "DelegationRuntime | None" = None) -> None:
        self.registry = registry
        self.runtime = runtime

    def delegate(
        self,
        pupil_name: str,
        user_message: str,
        task_id: str,
        parent_thread_id: str = "",
    ) -> DelegationResult:
        pupil = self.registry.get(pupil_name)
        try:
            if self.runtime is None:
                response = pupil.answer(user_message)
            else:
                run = self.runtime.delegate(
                    profile_id=pupil_name,
                    pupil=pupil,
                    goal=user_message,
                    parent_thread_id=parent_thread_id or task_id,
                    task_id=task_id,
                )
                response = run.response
        except Exception:
            logger.exception("Pupil %s failed during delegated task %s.", pupil_name, task_id)
            return DelegationResult(
                task_id=task_id,
                pupil=pupil_name,
                status="error",
                answer=f"{pupil_name} could not complete this delegated task.",
                confidence=0.0,
                sources=[],
                memory_proposals=[],
            )
        return DelegationResult(
            task_id=task_id,
            pupil=response.agent,
            status=response.status,
            answer=response.summary,
            confidence=response.confidence,
            sources=response.sources,
            memory_proposals=response.memory_proposals,
        )
