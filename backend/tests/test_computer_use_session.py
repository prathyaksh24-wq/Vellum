from __future__ import annotations

import pytest

from agent.computer_use_runtime import ComputerUseRuntime


class FakeOverlay:
    def __init__(self, *, fail_start: bool = False) -> None:
        self.fail_start = fail_start
        self.calls: list[str] = []

    def start(self) -> str:
        self.calls.append("start")
        if self.fail_start:
            raise RuntimeError("overlay unavailable")
        return "overlay started"

    def stop(self) -> str:
        self.calls.append("stop")
        return "overlay stopped"

    def status(self) -> dict[str, object]:
        return {"ready": "start" in self.calls and "stop" not in self.calls}


class FakeRouter:
    def __init__(self) -> None:
        self.tasks: list[str] = []

    def run_instruction(self, instruction: str, *, session_id: str) -> dict[str, object]:
        self.tasks.append(instruction)
        return {
            "status": "done",
            "session_id": session_id,
            "steps": [
                {"type": "screenshot", "message": "screen captured"},
                {"type": "action", "message": "opened notepad"},
            ],
        }


def _runtime(tmp_path):
    return ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )


def test_session_start_sets_active_status_and_starts_overlay(tmp_path):
    from agent.computer_use.session import ComputerUseSession

    overlay = FakeOverlay()
    runtime = _runtime(tmp_path)
    session = ComputerUseSession(runtime=runtime, overlay=overlay, router=FakeRouter())

    status = session.start(source="ui", thread_id="frontend", task="open browser")

    assert overlay.calls == ["start"]
    assert status["enabled"] is True
    assert status["status"] == "ready"
    assert status["session_id"]
    assert runtime.recent_events()[-1]["kind"] == "session_started"


def test_session_stop_cancels_work_and_stops_overlay(tmp_path):
    from agent.computer_use.session import ComputerUseSession

    overlay = FakeOverlay()
    runtime = _runtime(tmp_path)
    session = ComputerUseSession(runtime=runtime, overlay=overlay, router=FakeRouter())
    session.start(source="ui", thread_id="frontend")

    status = session.stop(source="ui", reason="user")

    assert overlay.calls == ["start", "stop"]
    assert status["enabled"] is False
    assert status["status"] == "disabled"
    assert session.stop_requested is True
    assert runtime.recent_events()[-1]["kind"] == "session_stopped"


def test_session_submit_task_records_ordered_events(tmp_path):
    from agent.computer_use.session import ComputerUseSession

    router = FakeRouter()
    runtime = _runtime(tmp_path)
    session = ComputerUseSession(runtime=runtime, overlay=FakeOverlay(), router=router)
    session.start(source="ui", thread_id="frontend")

    result = session.submit_task("open notepad", source="text", thread_id="frontend")

    assert router.tasks == ["open notepad"]
    assert result["status"] == "done"
    kinds = [event["kind"] for event in runtime.recent_events()]
    assert "task_started" in kinds
    assert "observation" in kinds
    assert "action_finished" in kinds
    assert kinds[-1] == "task_finished"


def test_session_start_failure_does_not_leave_mode_enabled(tmp_path):
    from agent.computer_use.session import ComputerUseSession, ComputerUseSessionError

    runtime = _runtime(tmp_path)
    session = ComputerUseSession(runtime=runtime, overlay=FakeOverlay(fail_start=True), router=FakeRouter())

    with pytest.raises(ComputerUseSessionError, match="overlay unavailable"):
        session.start(source="ui", thread_id="frontend")

    assert runtime.status()["enabled"] is False
    assert runtime.status()["status"] == "disabled"
