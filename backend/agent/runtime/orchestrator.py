from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from agent.organization.messages import TaskRoomService
from agent.profiles import ProfileRegistry
from agent.runtime.supervisor import AgentSupervisor


@dataclass(frozen=True)
class AgentTask:
    profile_id: str
    pupil: Any
    goal: str
    parent_thread_id: str
    context: str = ""
    task_id: str | None = None


@dataclass(frozen=True)
class BatchItem:
    index: int
    task: AgentTask
    result: Any | None = None
    error: str | None = None


@dataclass(frozen=True)
class DepartmentResult:
    department_id: str
    room_id: str
    contributions: tuple[BatchItem, ...]
    completion: dict[str, Any]


class AgentOrchestrator:
    def __init__(
        self,
        runtime: Any,
        profile_registry: ProfileRegistry,
        supervisor: AgentSupervisor,
        task_rooms: TaskRoomService,
        *,
        global_limit: int = 8,
        batch_limit: int = 16,
        department_limits: dict[str, int] | None = None,
    ) -> None:
        self.runtime = runtime
        self.profile_registry = profile_registry
        self.supervisor = supervisor
        self.task_rooms = task_rooms
        self.batch_limit = batch_limit
        self._global = asyncio.Semaphore(global_limit)
        self._department_limits = department_limits or {}
        self._departments: dict[str, asyncio.Semaphore] = {}
        self._profiles: dict[str, asyncio.Semaphore] = {}

    async def delegate(self, task: AgentTask, *, parent_task_id: str | None = None) -> Any:
        profile = self.profile_registry.get(task.profile_id)
        department = self._departments.setdefault(
            profile.department,
            asyncio.Semaphore(self._department_limits.get(profile.department, self._global._value)),
        )
        profile_limit = max(1, profile.delegation.max_concurrent_children or self._global._value)
        profile_gate = self._profiles.setdefault(profile.id, asyncio.Semaphore(profile_limit))
        async with self._global, department, profile_gate:
            kwargs = {
                "profile_id": task.profile_id,
                "pupil": task.pupil,
                "goal": task.goal,
                "parent_thread_id": task.parent_thread_id,
                "context": task.context,
                "task_id": task.task_id,
            }
            if parent_task_id is not None:
                kwargs["parent_task_id"] = parent_task_id
            return await asyncio.to_thread(self.runtime.delegate, **kwargs)

    async def delegate_batch(self, tasks: list[AgentTask], *, fail_fast: bool = False) -> list[BatchItem]:
        if len(tasks) > self.batch_limit:
            raise ValueError("batch limit exceeded")

        async def execute(index: int, task: AgentTask) -> BatchItem:
            try:
                return BatchItem(index=index, task=task, result=await self.delegate(task))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return BatchItem(index=index, task=task, error=exc.__class__.__name__)

        pending = [asyncio.create_task(execute(index, task)) for index, task in enumerate(tasks)]
        if not fail_fast:
            return sorted(await asyncio.gather(*pending), key=lambda item: item.index)

        results: list[BatchItem] = []
        for completed in asyncio.as_completed(pending):
            item = await completed
            results.append(item)
            if item.error:
                for future in pending:
                    if not future.done():
                        future.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                break
        return sorted(results, key=lambda item: item.index)

    async def delegate_department(self, department_id: str, goal: str, members: list[AgentTask]) -> DepartmentResult:
        if not members or any(self.profile_registry.get(member.profile_id).department != department_id for member in members):
            raise ValueError("department membership mismatch")
        room = self.task_rooms.create(owner="VellumAgent", purpose=goal, participants=[member.profile_id for member in members])
        contributions = await self.delegate_batch(members)
        for item in contributions:
            if item.result is None:
                continue
            response = item.result.response
            self.task_rooms.post(
                room.id, item.task.profile_id, "VellumAgent", "final_contribution",
                response.summary, [str(getattr(source, "path_or_url", "")) for source in response.sources if getattr(source, "path_or_url", "")],
                float(response.confidence),
            )
        completion = self.task_rooms.complete(room.id, actor="VellumAgent")
        return DepartmentResult(department_id, room.id, tuple(contributions), completion)

    async def delegate_child(self, parent_task_id: str, task: AgentTask) -> Any:
        parent = self.supervisor.status(parent_task_id)
        parent_profile = self.profile_registry.get(parent.agent_name)
        depth = self._depth(parent_task_id)
        if (
            not parent_profile.delegation.can_delegate
            or parent_profile.delegation.role != "orchestrator"
            or depth >= parent_profile.delegation.max_spawn_depth
        ):
            raise PermissionError("nested delegation unavailable")
        return await self.delegate(task, parent_task_id=parent_task_id)

    def _depth(self, task_id: str) -> int:
        depth = 0
        current = self.supervisor.status(task_id)
        while current.parent_task_id:
            depth += 1
            current = self.supervisor.status(current.parent_task_id)
        return depth
