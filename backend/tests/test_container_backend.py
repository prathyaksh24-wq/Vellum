from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from agent.runtime.container import ContainerBackend, ContainerPolicy


class Runner:
    def __init__(self, *, available=True, timeout=False):
        self.available = available
        self.timeout = timeout
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if argv[:2] == ["docker", "info"] and not self.available:
            return subprocess.CompletedProcess(argv, 1, "", "missing")
        if self.timeout and argv[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 1))
        return subprocess.CompletedProcess(argv, 0, "ok", "")


def test_container_command_is_hardened_allowlisted_and_has_explicit_mounts(tmp_path: Path):
    runner = Runner()
    policy = ContainerPolicy(allowed_images=frozenset({"vellum-agent:test"}), memory="256m", cpus="0.5", pids_limit=64)
    backend = ContainerBackend(policy=policy, runner=runner)

    backend.run(image="vellum-agent:test", agent_home=tmp_path / "agent", workspace=tmp_path / "work", payload={"goal": "test"})

    command = runner.calls[1][0]
    assert command[:3] == ["docker", "run", "--rm"]
    assert "--read-only" in command
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--pids-limit") + 1] == "64"
    assert command[command.index("--memory") + 1] == "256m"
    assert command[command.index("--cpus") + 1] == "0.5"
    assert any("dst=/workspace,readonly" in value for value in command)
    assert any("dst=/agent-home" in value and "readonly" not in value for value in command)
    assert not any("OPENROUTER" in value or "API_KEY" in value for value in command)


def test_container_rejects_unapproved_image_and_fails_closed_without_docker(tmp_path: Path):
    backend = ContainerBackend(policy=ContainerPolicy(allowed_images=frozenset({"approved"})), runner=Runner())
    with pytest.raises(PermissionError, match="container unavailable"):
        backend.run(image="unapproved", agent_home=tmp_path / "a", workspace=tmp_path / "w", payload={})

    unavailable = ContainerBackend(policy=ContainerPolicy(allowed_images=frozenset({"approved"})), runner=Runner(available=False))
    with pytest.raises(RuntimeError, match="container unavailable"):
        unavailable.run(image="approved", agent_home=tmp_path / "a", workspace=tmp_path / "w", payload={})


def test_container_timeout_cleans_exact_generated_container(tmp_path: Path):
    runner = Runner(timeout=True)
    backend = ContainerBackend(policy=ContainerPolicy(allowed_images=frozenset({"approved"})), runner=runner)
    with pytest.raises(TimeoutError):
        backend.run(image="approved", agent_home=tmp_path / "a", workspace=tmp_path / "w", payload={}, timeout=0.01)
    run_command = runner.calls[1][0]
    name = run_command[run_command.index("--name") + 1]
    assert runner.calls[-1][0] == ["docker", "rm", "-f", name]
