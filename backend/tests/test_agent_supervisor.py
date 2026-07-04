from __future__ import annotations

from pathlib import Path
import time

from agent.runtime.supervisor import AgentSupervisor


def test_supervisor_persists_lifecycle_result_heartbeats_and_iterations(tmp_path: Path):
    supervisor = AgentSupervisor(tmp_path / "tasks.db", monitor_interval=0.01)

    def work(control):
        control.heartbeat()
        control.operation("model")
        control.operation("tool")
        return {"answer": 42}

    task_id = supervisor.submit(run_id="run", agent_name="ResearchAgent", department="research", work=work, max_iterations=3)
    record = supervisor.wait(task_id, timeout=2)

    assert record.state == "completed"
    assert record.result == {"answer": 42}
    assert record.iterations == 2
    assert record.heartbeat_at is not None
    assert supervisor.status(task_id).state == "completed"


def test_supervisor_enforces_iteration_and_deadline_budgets(tmp_path: Path):
    supervisor = AgentSupervisor(tmp_path / "tasks.db", monitor_interval=0.01)

    def too_many(control):
        control.operation("model")
        control.operation("tool")

    exhausted = supervisor.submit(run_id="run", agent_name="A", department="d", work=too_many, max_iterations=1)
    assert supervisor.wait(exhausted, timeout=2).state == "failed"

    def slow(control):
        while not control.cancelled:
            time.sleep(0.01)

    timed = supervisor.submit(run_id="run", agent_name="B", department="d", work=slow, timeout_seconds=0.05)
    assert supervisor.wait(timed, timeout=2).state == "timed_out"


def test_timeout_zero_disables_deadline(tmp_path: Path):
    supervisor = AgentSupervisor(tmp_path / "tasks.db", monitor_interval=0.01)
    task = supervisor.submit(run_id="run", agent_name="A", department="d", work=lambda control: "ok", timeout_seconds=0)
    assert supervisor.wait(task, timeout=2).state == "completed"
