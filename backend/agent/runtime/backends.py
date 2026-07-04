from __future__ import annotations

import os
from pathlib import Path
from queue import Empty, Queue
import secrets
import subprocess
import sys
from threading import Thread
import time
from typing import Any

from agent.runtime.protocol import ProtocolMessage, encode_message, parse_message, validate_envelope


class WorkerAuthenticationError(RuntimeError):
    pass


class SubprocessHandle:
    def __init__(self, process: subprocess.Popen[str], *, run_id: str, task_id: str, token: str, cancellation_grace: float) -> None:
        self.process = process
        self.run_id = run_id
        self.task_id = task_id
        self._token = token
        self.cancellation_grace = cancellation_grace
        self.authenticated = False
        self._messages: Queue[ProtocolMessage | BaseException | None] = Queue()
        self.stderr: list[str] = []
        Thread(target=self._read_stdout, daemon=True).start()
        Thread(target=self._read_stderr, daemon=True).start()

    def authenticate(self, timeout: float = 15.0) -> None:
        message = self.read(timeout=timeout, validate=False)
        if message.type != "progress" or message.payload.get("event") != "hello" or not secrets.compare_digest(str(message.payload.get("token", "")), self._token):
            self.terminate()
            raise WorkerAuthenticationError("worker authentication failed")
        self.authenticated = True

    def start_run(self, payload: dict[str, Any]) -> None:
        self.send("run", {**payload, "auth_token": self._token})

    def send(self, message_type: str, payload: dict[str, Any]) -> None:
        if self.process.stdin is None or self.process.poll() is not None:
            raise RuntimeError("worker unavailable")
        self.process.stdin.write(encode_message(message_type, self.run_id, self.task_id, payload) + "\n")
        self.process.stdin.flush()

    def read(self, timeout: float | None = None, *, validate: bool = True) -> ProtocolMessage:
        try:
            item = self._messages.get(timeout=timeout)
        except Empty as exc:
            raise TimeoutError("worker message timeout") from exc
        if isinstance(item, BaseException):
            raise item
        if item is None:
            raise EOFError("worker closed")
        return validate_envelope(item, run_id=self.run_id, task_id=self.task_id) if validate else item

    def cancel(self) -> None:
        if self.poll() is None:
            self.send("cancel", {"reason": "supervisor_cancelled"})

    def terminate(self) -> None:
        if self.process.poll() is not None:
            return
        try:
            self.cancel()
            self.process.wait(timeout=self.cancellation_grace)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)

    def poll(self) -> int | None:
        return self.process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                if line.strip():
                    self._messages.put(parse_message(line))
        except BaseException as exc:
            self._messages.put(exc)
        finally:
            self._messages.put(None)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        self.stderr.extend(line.rstrip() for line in self.process.stderr)


class SubprocessBackend:
    def __init__(self, *, heartbeat_interval: float = 1.0, cancellation_grace: float = 2.0, python_executable: str | None = None) -> None:
        self.heartbeat_interval = heartbeat_interval
        self.cancellation_grace = cancellation_grace
        self.python_executable = python_executable or sys.executable

    def start(self, *, run_id: str, task_id: str, agent_home: Path, payload: dict[str, Any]) -> SubprocessHandle:
        home = Path(agent_home).resolve()
        home.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(32)
        environment = _sanitized_environment(token, self.heartbeat_interval)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            [self.python_executable, "-u", "-m", "agent.runtime.worker", "--run-id", run_id, "--task-id", task_id],
            cwd=str(home), env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, creationflags=creationflags,
        )
        handle = SubprocessHandle(process, run_id=run_id, task_id=task_id, token=token, cancellation_grace=self.cancellation_grace)
        handle.authenticate()
        handle.start_run(payload)
        return handle


def _sanitized_environment(token: str, heartbeat_interval: float) -> dict[str, str]:
    allowed = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    backend_root = str(Path(__file__).resolve().parents[2])
    env.update({
        "PYTHONPATH": backend_root,
        "PYTHONIOENCODING": "utf-8",
        "VELLUM_WORKER_TOKEN": token,
        "VELLUM_HEARTBEAT_INTERVAL": str(heartbeat_interval),
    })
    return env
