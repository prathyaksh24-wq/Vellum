from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from agent.agents.base import SpecialistResponse
from agent.profiles import ActivatedSkill, AgentProfile, IdentityStack


@dataclass(frozen=True)
class CancellationView:
    _cancelled: Callable[[], bool]

    @property
    def cancelled(self) -> bool:
        return bool(self._cancelled())

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RuntimeError("delegation cancelled")


@dataclass(frozen=True)
class AgentExecutionContext:
    run_id: str
    task_id: str
    parent_task_id: str | None
    goal: str
    explicit_context: str
    profile: AgentProfile
    prompt_stack: IdentityStack
    skills: tuple[ActivatedSkill, ...]
    memory_refs: tuple[str, ...]
    task_room_id: str | None
    deadline: datetime | None
    max_iterations: int
    cancellation: CancellationView


def invoke_specialist(pupil: Any, context: AgentExecutionContext) -> SpecialistResponse:
    context.cancellation.raise_if_cancelled()
    answer_task = getattr(pupil, "answer_task", None)
    if callable(answer_task):
        return answer_task(context)
    return pupil.answer(context.goal)
