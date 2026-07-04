from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
import secrets
import subprocess
from typing import Any


@dataclass(frozen=True)
class ContainerPolicy:
    allowed_images: frozenset[str]
    memory: str = "512m"
    cpus: str = "1.0"
    pids_limit: int = 128
    allow_subprocess_fallback: bool = False


class ContainerBackend:
    def __init__(
        self,
        *,
        policy: ContainerPolicy,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        subprocess_fallback: Any | None = None,
    ) -> None:
        self.policy = policy
        self.runner = runner
        self.subprocess_fallback = subprocess_fallback

    def available(self) -> bool:
        try:
            result = self.runner(
                ["docker", "info"], capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def run(
        self,
        *,
        image: str,
        agent_home: Path,
        workspace: Path,
        payload: dict[str, Any],
        timeout: float = 300,
    ) -> subprocess.CompletedProcess[str] | Any:
        if image not in self.policy.allowed_images:
            raise PermissionError("container unavailable")
        if not self.available():
            if self.policy.allow_subprocess_fallback and self.subprocess_fallback is not None:
                return self.subprocess_fallback(payload=payload, agent_home=agent_home, workspace=workspace)
            raise RuntimeError("container unavailable")

        home = Path(agent_home).resolve()
        root = Path(workspace).resolve()
        home.mkdir(parents=True, exist_ok=True)
        name = f"vellum-agent-{secrets.token_hex(8)}"
        command = self.build_command(image=image, agent_home=home, workspace=root, name=name)
        try:
            result = self.runner(
                command,
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            self.runner(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=10)
            raise TimeoutError("container timed out") from exc
        if result.returncode != 0:
            raise RuntimeError("container unavailable")
        return result

    def build_command(self, *, image: str, agent_home: Path, workspace: Path, name: str) -> list[str]:
        if image not in self.policy.allowed_images:
            raise PermissionError("container unavailable")
        return [
            "docker", "run", "--rm",
            "--name", name,
            "--read-only",
            "--network", "none",
            "--pids-limit", str(self.policy.pids_limit),
            "--memory", self.policy.memory,
            "--cpus", self.policy.cpus,
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--mount", f"type=bind,src={workspace},dst=/workspace,readonly",
            "--mount", f"type=bind,src={agent_home},dst=/agent-home",
            "--workdir", "/agent-home",
            image,
        ]
