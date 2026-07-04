from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest

from agent.organization.messages import TaskRoomService
from agent.organization.store import OrganizationStore
from agent.profiles import AgentProfile, DelegationPolicy, ProfileRegistry
from agent.runtime.orchestrator import AgentOrchestrator, AgentTask
from agent.runtime.supervisor import AgentSupervisor


class FakeRuntime:
    def __init__(self):
        self.active = 0
        self.maximum = 0
        self.lock = threading.Lock()

    def delegate(self, **kwargs):
        with self.lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
        try:
            time.sleep(0.04)
            if kwargs["goal"] == "fail":
                raise RuntimeError("failed deliberately")
            response = SimpleNamespace(summary=f"answer:{kwargs['goal']}", confidence=0.8, sources=[])
            return SimpleNamespace(task_id=kwargs.get("task_id") or kwargs["goal"], response=response)
        finally:
            with self.lock:
                self.active -= 1


def _orchestrator(tmp_path: Path, *, global_limit=2, batch_limit=4):
    runtime = FakeRuntime()
    profiles = {
        "A": AgentProfile(id="A", department="research"),
        "B": AgentProfile(id="B", department="research"),
        "Lead": AgentProfile(id="Lead", department="research", delegation=DelegationPolicy(can_delegate=True, role="orchestrator", max_concurrent_children=2, max_spawn_depth=2)),
    }
    registry = ProfileRegistry(tmp_path / "profiles", builtins=profiles)
    supervisor = AgentSupervisor(tmp_path / "tasks.db", monitor_interval=0.01)
    rooms = TaskRoomService(OrganizationStore(tmp_path / "org.db"))
    return AgentOrchestrator(runtime, registry, supervisor, rooms, global_limit=global_limit, batch_limit=batch_limit), runtime, supervisor, rooms


def test_parallel_batch_caps_concurrency_preserves_order_and_attributes_failures(tmp_path: Path):
    orchestrator, runtime, _, _ = _orchestrator(tmp_path, global_limit=2)
    tasks = [AgentTask("A", None, goal, "thread") for goal in ("one", "fail", "three")]

    results = asyncio.run(orchestrator.delegate_batch(tasks))

    assert [item.index for item in results] == [0, 1, 2]
    assert results[0].result.response.summary == "answer:one"
    assert results[1].error == "RuntimeError"
    assert results[2].result.response.summary == "answer:three"
    assert runtime.maximum == 2


def test_batch_limit_is_enforced(tmp_path: Path):
    orchestrator, _, _, _ = _orchestrator(tmp_path, batch_limit=1)
    with pytest.raises(ValueError, match="batch limit"):
        asyncio.run(orchestrator.delegate_batch([AgentTask("A", None, "1", "t"), AgentTask("A", None, "2", "t")]))


def test_department_delegation_creates_attributed_room_contributions(tmp_path: Path):
    orchestrator, _, _, rooms = _orchestrator(tmp_path)
    result = asyncio.run(orchestrator.delegate_department("research", "compare", [AgentTask("A", None, "one", "t"), AgentTask("B", None, "two", "t")]))

    messages = rooms.store.messages(result.room_id)
    assert {message.sender for message in messages} == {"A", "B"}
    assert all(message.type == "final_contribution" for message in messages)
    assert result.completion["published"] == []


def test_nested_delegation_requires_orchestrator_role_and_depth(tmp_path: Path):
    orchestrator, _, supervisor, _ = _orchestrator(tmp_path)
    parent = supervisor.submit(run_id="r", agent_name="Lead", department="research", work=lambda control: "done")
    supervisor.wait(parent, timeout=2)
    child = asyncio.run(orchestrator.delegate_child(parent, AgentTask("A", None, "child", "t")))
    assert child.response.summary == "answer:child"

    leaf = supervisor.submit(run_id="r", agent_name="A", department="research", work=lambda control: "done")
    supervisor.wait(leaf, timeout=2)
    with pytest.raises(PermissionError, match="nested delegation unavailable"):
        asyncio.run(orchestrator.delegate_child(leaf, AgentTask("B", None, "child", "t")))
