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


class FakeInterruptOverlay(FakeOverlay):
    def __init__(self) -> None:
        super().__init__()
        self.interrupt_callback = None

    def set_interrupt_callback(self, callback) -> None:
        self.interrupt_callback = callback


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


class FakeInputGuard:
    def __init__(self, *, fail_acquire: bool = False) -> None:
        self.fail_acquire = fail_acquire
        self.calls: list[str] = []
        self.on_interrupt = None
        self.active = False

    def acquire(self, *, session_id: str, on_interrupt):
        self.calls.append(f"acquire:{session_id}")
        if self.fail_acquire:
            raise RuntimeError("input guard unavailable")
        self.on_interrupt = on_interrupt
        self.active = True
        return "input guard acquired"

    def release(self) -> str:
        self.calls.append("release")
        self.active = False
        return "input guard released"

    def heartbeat(self) -> None:
        self.calls.append("heartbeat")

    def status(self) -> dict[str, object]:
        return {"ready": True, "active": self.active, "lease_active": self.active}

    def interrupt(self) -> None:
        assert self.on_interrupt is not None
        self.on_interrupt("kill switch")


def _runtime(tmp_path):
    return ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )


def test_session_start_sets_active_status_and_starts_overlay(tmp_path):
    from agent.computer_use.session import ComputerUseSession

    overlay = FakeOverlay()
    runtime = _runtime(tmp_path)
    guard = FakeInputGuard()
    session = ComputerUseSession(runtime=runtime, overlay=overlay, router=FakeRouter(), input_guard=guard)

    status = session.start(source="ui", thread_id="frontend", task="open browser")

    assert overlay.calls == ["start"]
    assert guard.calls[0].startswith("acquire:")
    assert status["enabled"] is True
    assert status["status"] == "ready"
    assert status["session_id"]
    assert status["input_guard"]["lease_active"] is True
    assert runtime.recent_events()[-1]["kind"] == "session_started"


def test_session_stop_cancels_work_and_stops_overlay(tmp_path):
    from agent.computer_use.session import ComputerUseSession

    overlay = FakeOverlay()
    runtime = _runtime(tmp_path)
    guard = FakeInputGuard()
    session = ComputerUseSession(runtime=runtime, overlay=overlay, router=FakeRouter(), input_guard=guard)
    session.start(source="ui", thread_id="frontend")

    status = session.stop(source="ui", reason="user")

    assert overlay.calls == ["start", "stop"]
    assert guard.calls[-1] == "release"
    assert status["enabled"] is False
    assert status["status"] == "disabled"
    assert session.stop_requested is True
    assert runtime.recent_events()[-1]["kind"] == "session_stopped"


def test_session_stop_is_idempotent_and_records_single_stop_event(tmp_path):
    from agent.computer_use.session import ComputerUseSession

    overlay = FakeOverlay()
    runtime = _runtime(tmp_path)
    guard = FakeInputGuard()
    session = ComputerUseSession(runtime=runtime, overlay=overlay, router=FakeRouter(), input_guard=guard)
    session.start(source="ui", thread_id="frontend")

    first = session.stop(source="overlay", reason="esc")
    second = session.stop(source="input_guard", reason="kill switch")

    assert first["enabled"] is False
    assert second["enabled"] is False
    assert overlay.calls == ["start", "stop"]
    assert guard.calls.count("release") == 1
    stop_events = [event for event in runtime.recent_events() if event["kind"] == "session_stopped"]
    assert len(stop_events) == 1
    assert stop_events[0]["data"]["source"] == "overlay"


def test_session_submit_task_records_ordered_events(tmp_path):
    from agent.computer_use.session import ComputerUseSession

    router = FakeRouter()
    runtime = _runtime(tmp_path)
    session = ComputerUseSession(runtime=runtime, overlay=FakeOverlay(), router=router, input_guard=FakeInputGuard())
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
    session = ComputerUseSession(
        runtime=runtime,
        overlay=FakeOverlay(fail_start=True),
        router=FakeRouter(),
        input_guard=FakeInputGuard(),
    )

    with pytest.raises(ComputerUseSessionError, match="overlay unavailable"):
        session.start(source="ui", thread_id="frontend")

    assert runtime.status()["enabled"] is False
    assert runtime.status()["status"] == "disabled"


def test_session_guard_failure_stops_overlay_and_does_not_enable_mode(tmp_path):
    from agent.computer_use.session import ComputerUseSession, ComputerUseSessionError

    overlay = FakeOverlay()
    runtime = _runtime(tmp_path)
    session = ComputerUseSession(
        runtime=runtime,
        overlay=overlay,
        router=FakeRouter(),
        input_guard=FakeInputGuard(fail_acquire=True),
    )

    with pytest.raises(ComputerUseSessionError, match="input guard unavailable"):
        session.start(source="ui", thread_id="frontend")

    assert overlay.calls == ["start", "stop"]
    assert runtime.status()["enabled"] is False
    assert runtime.status()["status"] == "disabled"


def test_session_guard_interrupt_force_stops_computer_use(tmp_path):
    from agent.computer_use.session import ComputerUseSession

    overlay = FakeOverlay()
    guard = FakeInputGuard()
    runtime = _runtime(tmp_path)
    session = ComputerUseSession(runtime=runtime, overlay=overlay, router=FakeRouter(), input_guard=guard)
    session.start(source="ui", thread_id="frontend")

    guard.interrupt()

    status = runtime.status()
    assert status["enabled"] is False
    assert status["status"] == "disabled"
    assert status["source"] == "input_guard"
    assert overlay.calls == ["start", "stop"]
    assert guard.calls[-1] == "release"


def test_session_overlay_esc_interrupt_stops_computer_use(tmp_path):
    from agent.computer_use.session import ComputerUseSession

    overlay = FakeInterruptOverlay()
    guard = FakeInputGuard()
    runtime = _runtime(tmp_path)
    session = ComputerUseSession(runtime=runtime, overlay=overlay, router=FakeRouter(), input_guard=guard)
    session.start(source="ui", thread_id="frontend")

    assert overlay.interrupt_callback is not None
    overlay.interrupt_callback("esc")

    status = runtime.status()
    assert status["enabled"] is False
    assert status["status"] == "disabled"
    assert status["source"] == "overlay"
    assert overlay.calls == ["start", "stop"]


def test_native_overlay_script_uses_transparent_glow_and_status_pill():
    from agent.computer_use.native_windows import overlay

    script = overlay._overlay_script()

    assert "Vellum is using your computer" in overlay.OVERLAY_MESSAGE
    assert "TRANSPARENT_COLOR" in script
    assert "root.attributes(\"-transparentcolor\", TRANSPARENT_COLOR)" in script
    assert "root.configure(bg=TRANSPARENT_COLOR)" in script
    assert "canvas = tk.Canvas" in script
    assert "bg=TRANSPARENT_COLOR" in script
    assert "ImageDraw" in script
    assert "ImageTk.PhotoImage" in script
    assert "EDGE_GLOW_DESIGN" in script
    assert "pill_y1 = PILL_OFFSET_Y" in script or "pill_y1 = 32" in script
    assert "for inset, color, line_width in" not in script
    assert "create_rounded_rect" in script
    assert "root.after" in script
    assert "Computer use active - press Esc to exit" not in script
    assert "canvas.create_text(\n    width // 2,\n    height // 2" not in script


def test_native_overlay_status_reports_transparent_glow_design():
    from agent.computer_use.native_windows.overlay import NativeWindowsOverlayController

    status = NativeWindowsOverlayController().status()

    assert status["controller"] == "native_windows"
    assert status["design"] == "transparent_edge_glow_status_pill"
    assert status["transparent"] is True
    assert status["click_through"] is True
    assert "Vellum is using your computer" in status["message"]
