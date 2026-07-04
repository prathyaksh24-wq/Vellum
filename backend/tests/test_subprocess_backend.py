from __future__ import annotations

import os
from pathlib import Path
import time

from agent.runtime.backends import SubprocessBackend


def _next_type(handle, wanted: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = handle.read(timeout=0.5)
        if message.type == wanted:
            return message
    raise AssertionError(f"did not receive {wanted}")


def test_subprocess_authenticates_uses_dedicated_home_and_sanitizes_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-not-cross")
    home = tmp_path / "agent-home"
    backend = SubprocessBackend(heartbeat_interval=0.05)
    handle = backend.start(run_id="run", task_id="task", agent_home=home, payload={"inspect_environment": True})
    try:
        result = _next_type(handle, "result")
        assert result.payload["cwd"] == str(home.resolve())
        assert result.payload["has_openrouter_key"] is False
        assert handle.authenticated is True
    finally:
        handle.terminate()


def test_subprocess_heartbeats_broker_roundtrip_and_graceful_cancel(tmp_path: Path):
    backend = SubprocessBackend(heartbeat_interval=0.05, cancellation_grace=0.5)
    handle = backend.start(
        run_id="run", task_id="task", agent_home=tmp_path / "home",
        payload={"sleep": 2.0, "tool_request": {"name": "echo", "payload": {"value": 7}}},
    )
    try:
        request = _next_type(handle, "tool_request")
        handle.send("tool_result", {"request_id": request.payload["request_id"], "result": {"value": 7}})
        _next_type(handle, "heartbeat")
        handle.cancel()
        result = _next_type(handle, "result")
        assert result.payload["status"] == "cancelled"
    finally:
        handle.terminate()


def test_terminating_one_worker_does_not_kill_sibling(tmp_path: Path):
    backend = SubprocessBackend(heartbeat_interval=0.05)
    first = backend.start(run_id="run", task_id="one", agent_home=tmp_path / "one", payload={"sleep": 3.0})
    second = backend.start(run_id="run", task_id="two", agent_home=tmp_path / "two", payload={"sleep": 3.0})
    try:
        first.terminate()
        assert first.poll() is not None
        assert second.poll() is None
    finally:
        second.terminate()
