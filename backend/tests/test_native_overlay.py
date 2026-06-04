from __future__ import annotations

from pathlib import Path
import threading

import pytest


class FakeProcess:
    def __init__(self, *, running: bool = True) -> None:
        self.running = running
        self.pid = 1234
        self.terminated = False

    def poll(self):
        return None if self.running else 1

    def terminate(self) -> None:
        self.terminated = True
        self.running = False

    def wait(self, timeout=None):
        self.running = False
        return 0

    def kill(self) -> None:
        self.running = False


class CapturedThread:
    instances: list["CapturedThread"] = []

    def __init__(self, *, target, args=(), daemon=None) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False
        self.join_calls: list[float | None] = []
        CapturedThread.instances.append(self)

    def start(self) -> None:
        self.started = True

    def join(self, timeout=None) -> None:
        self.join_calls.append(timeout)


def test_native_overlay_start_fails_closed_when_child_exits_immediately(monkeypatch):
    from agent.computer_use.native_windows import overlay

    monkeypatch.setattr(overlay, "_activity_overlay_enabled", lambda: True)
    monkeypatch.setattr(overlay.subprocess, "Popen", lambda *args, **kwargs: FakeProcess(running=False))
    monkeypatch.setattr(overlay.time, "sleep", lambda _seconds: None)

    controller = overlay.NativeWindowsOverlayController()

    with pytest.raises(RuntimeError, match="could not be started"):
        controller.start()

    assert controller.status()["ready"] is False


def test_native_overlay_restart_joins_old_watcher_and_uses_per_run_state(monkeypatch):
    from agent.computer_use.native_windows import overlay

    CapturedThread.instances.clear()
    first_process = FakeProcess(running=True)
    processes = [first_process, FakeProcess(running=True)]

    monkeypatch.setattr(overlay, "_activity_overlay_enabled", lambda: True)
    monkeypatch.setattr(overlay.subprocess, "Popen", lambda *args, **kwargs: processes.pop(0))
    monkeypatch.setattr(overlay.threading, "Thread", CapturedThread)
    monkeypatch.setattr(overlay.time, "sleep", lambda _seconds: None)

    controller = overlay.NativeWindowsOverlayController()
    assert controller.start() == "Computer-use activity overlay started."

    first_watcher = CapturedThread.instances[0]
    assert first_watcher.started is True

    first_process.running = False
    assert controller.start() == "Computer-use activity overlay started."

    assert first_watcher.join_calls, "old watcher should be joined before restart"
    assert len(CapturedThread.instances) == 2
    assert len(CapturedThread.instances[1].args) == 4


def test_native_overlay_stale_watcher_does_not_fire_after_restart(tmp_path):
    from agent.computer_use.native_windows.overlay import NativeWindowsOverlayController

    controller = NativeWindowsOverlayController()
    callbacks: list[str] = []
    controller.set_interrupt_callback(callbacks.append)

    stale_sentinel = tmp_path / "stale.interrupt"
    stale_sentinel.write_text("esc", encoding="utf-8")
    current_sentinel = tmp_path / "current.interrupt"
    stale_process = FakeProcess(running=True)
    current_process = FakeProcess(running=True)
    stale_stop_event = threading.Event()
    stale_generation = 1

    with controller._lock:
        controller._process = current_process
        controller._sentinel = current_sentinel
        controller._generation = stale_generation + 1

    controller._watch_for_interrupt(stale_stop_event, stale_process, Path(stale_sentinel), stale_generation)

    assert callbacks == []


def test_native_overlay_status_reports_smooth_single_edge_glow_design():
    from agent.computer_use.native_windows.overlay import NativeWindowsOverlayController

    status = NativeWindowsOverlayController().status()

    assert status["design"] == "smooth_single_edge_glow_status_pill"
    assert status["edge_glow"] is True
    assert status["status_pill"] is True
    assert status["pill_offset_y"] == 32
    assert status["edge_glow_style"] == "smooth-single"
