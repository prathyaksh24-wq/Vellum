from pathlib import Path
import time

from agent.runtime.supervisor import AgentSupervisor


def _wait_until_running(supervisor, task_id):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if supervisor.status(task_id).state == "running":
            return
        time.sleep(0.01)
    raise AssertionError("task did not start")


def test_recursive_cancel_stops_descendants_but_not_siblings(tmp_path: Path):
    supervisor = AgentSupervisor(tmp_path / "tasks.db", monitor_interval=0.01)

    def waiting(control):
        while not control.cancelled:
            control.heartbeat()
            time.sleep(0.01)
        return "stopped"

    parent = supervisor.submit(run_id="run", agent_name="Parent", department="d", work=waiting)
    child = supervisor.submit(run_id="run", agent_name="Child", department="d", parent_task_id=parent, work=waiting)
    sibling = supervisor.submit(run_id="run", agent_name="Sibling", department="d", work=waiting)
    _wait_until_running(supervisor, parent)
    _wait_until_running(supervisor, child)
    supervisor.cancel(parent, recursive=True)

    assert supervisor.wait(parent, timeout=2).state == "cancelled"
    assert supervisor.wait(child, timeout=2).state == "cancelled"
    assert supervisor.status(sibling).state == "running"
    supervisor.cancel(sibling)
