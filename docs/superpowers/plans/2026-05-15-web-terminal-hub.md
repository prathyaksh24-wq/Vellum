# Web Terminal Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a web terminal workspace with multiple shell profiles, tabbed sessions, slash-command shell switching, and a `vellum` command that opens the Vellum terminal UI surface.

**Architecture:** Backend terminal concerns live under `backend/agent/terminal/`, with profile detection separated from process/session lifecycle. FastAPI exposes profile metadata and one WebSocket terminal endpoint. Frontend terminal behavior is isolated in small ES modules and mounted from the existing `ui/vellum-chat.html` shell without rewriting the chat app.

**Tech Stack:** FastAPI WebSocket, pytest, optional Windows `pywinpty`, Vite, `@xterm/xterm`, `@xterm/addon-fit`, Vitest, jsdom.

---

## File Structure

- Create `backend/agent/terminal/__init__.py`: terminal package exports.
- Create `backend/agent/terminal/profiles.py`: shell profile model, aliases, and availability detection.
- Create `backend/agent/terminal/session.py`: session lifecycle, process transport abstraction, subprocess fallback, and optional WinPTY transport.
- Create `backend/tests/test_terminal_profiles.py`: profile catalog tests.
- Create `backend/tests/test_terminal_session.py`: session lifecycle tests using a fake transport.
- Create `backend/tests/test_terminal_api.py`: HTTP and WebSocket route tests with a fake session manager.
- Modify `backend/agent/api.py`: include terminal routes and dependency wiring.
- Modify `backend/pyproject.toml`: add `pywinpty` dependency for Windows PTY support.
- Modify `frontend/package.json`: add `@xterm/xterm`, `@xterm/addon-fit`, `vitest`, `jsdom`, and `test` script.
- Create `frontend/ui/terminal/commands.js`: pure parser for slash commands and `vellum`.
- Create `frontend/ui/terminal/terminal-workspace.js`: terminal tab UI, WebSocket client, xterm mount, shell switching, Vellum mode mount.
- Create `frontend/ui/terminal/commands.test.js`: parser tests.
- Create `frontend/ui/terminal/terminal-workspace.test.js`: DOM-level workspace tests with a fake terminal adapter.
- Modify `frontend/ui/vellum-chat.html`: add sidebar `Terminal` item, terminal surface container, terminal styles, and lazy module bootstrapping.
- Copy or import existing `Vellum TUI` assets into `frontend/ui/terminal/vellum/` only if direct relative imports from `Vellum TUI` cannot be served by Vite root rules. Prefer copy during implementation because Vite root is `frontend`.

---

### Task 1: Backend Shell Profile Catalog

**Files:**
- Create: `backend/agent/terminal/__init__.py`
- Create: `backend/agent/terminal/profiles.py`
- Test: `backend/tests/test_terminal_profiles.py`

- [ ] **Step 1: Write the failing profile catalog tests**

Create `backend/tests/test_terminal_profiles.py`:

```python
from pathlib import Path

from agent.terminal.profiles import (
    DEFAULT_CWD,
    PROFILE_ALIASES,
    TerminalProfile,
    get_profile,
    list_profiles,
)


def test_default_cwd_points_at_repo_root():
    assert DEFAULT_CWD.name == "Vellum"
    assert (DEFAULT_CWD / "backend").exists()
    assert (DEFAULT_CWD / "frontend").exists()


def test_catalog_contains_expected_profile_ids(monkeypatch):
    monkeypatch.setattr("agent.terminal.profiles._which", lambda name: f"C:/bin/{name}.exe")
    monkeypatch.setattr("agent.terminal.profiles._wsl_distros", lambda: ["Ubuntu"])
    monkeypatch.delenv("VELLUM_MACOS_SSH_TARGET", raising=False)

    profiles = {profile.id: profile for profile in list_profiles()}

    assert set(profiles) == {"powershell", "cmd", "pwsh", "wsl", "git-bash", "macos"}
    assert profiles["powershell"].available is True
    assert profiles["cmd"].available is True
    assert profiles["pwsh"].available is True
    assert profiles["wsl"].available is True
    assert profiles["git-bash"].available is True
    assert profiles["macos"].available is False
    assert "SSH target" in profiles["macos"].reason


def test_unavailable_profiles_include_reason(monkeypatch):
    monkeypatch.setattr("agent.terminal.profiles._which", lambda name: None)
    monkeypatch.setattr("agent.terminal.profiles._wsl_distros", lambda: [])
    monkeypatch.delenv("VELLUM_MACOS_SSH_TARGET", raising=False)

    profiles = {profile.id: profile for profile in list_profiles()}

    assert profiles["pwsh"].available is False
    assert "pwsh.exe" in profiles["pwsh"].reason
    assert profiles["wsl"].available is False
    assert "WSL" in profiles["wsl"].reason
    assert profiles["git-bash"].available is False
    assert "Git Bash" in profiles["git-bash"].reason


def test_macos_profile_uses_ssh_target_from_environment(monkeypatch):
    monkeypatch.setattr("agent.terminal.profiles._which", lambda name: f"C:/bin/{name}.exe")
    monkeypatch.setenv("VELLUM_MACOS_SSH_TARGET", "archit@mac-mini.local")

    profile = get_profile("mac")

    assert profile.id == "macos"
    assert profile.available is True
    assert profile.command == "ssh"
    assert profile.args == ["archit@mac-mini.local"]


def test_profile_aliases_resolve_to_canonical_ids(monkeypatch):
    monkeypatch.setattr("agent.terminal.profiles._which", lambda name: f"C:/bin/{name}.exe")
    monkeypatch.setattr("agent.terminal.profiles._wsl_distros", lambda: ["Ubuntu"])

    assert PROFILE_ALIASES["ubuntu"] == "wsl"
    assert get_profile("ps").id == "powershell"
    assert get_profile("bash").id == "git-bash"
    assert get_profile("unknown") is None


def test_terminal_profile_serializes_for_api():
    profile = TerminalProfile(
        id="powershell",
        label="PowerShell",
        command="powershell.exe",
        args=["-NoLogo"],
        cwd=Path("C:/work"),
        available=True,
        reason=None,
    )

    assert profile.to_public_dict() == {
        "id": "powershell",
        "label": "PowerShell",
        "available": True,
        "reason": None,
        "cwd": "C:\\work",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd backend
python -m pytest tests/test_terminal_profiles.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent.terminal'`.

- [ ] **Step 3: Create the terminal package export**

Create `backend/agent/terminal/__init__.py`:

```python
"""Web terminal support for Vellum."""

from agent.terminal.profiles import TerminalProfile, get_profile, list_profiles

__all__ = ["TerminalProfile", "get_profile", "list_profiles"]
```

- [ ] **Step 4: Implement the profile catalog**

Create `backend/agent/terminal/profiles.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess


DEFAULT_CWD = Path(__file__).resolve().parents[3]

PROFILE_ALIASES = {
    "powershell": "powershell",
    "ps": "powershell",
    "cmd": "cmd",
    "pwsh": "pwsh",
    "ubuntu": "wsl",
    "wsl": "wsl",
    "bash": "git-bash",
    "git-bash": "git-bash",
    "mac": "macos",
    "macos": "macos",
}


@dataclass(frozen=True)
class TerminalProfile:
    id: str
    label: str
    command: str
    args: list[str]
    cwd: Path
    available: bool
    reason: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "available": self.available,
            "reason": self.reason,
            "cwd": str(self.cwd),
        }


def _which(name: str) -> str | None:
    return shutil.which(name)


def _wsl_distros() -> list[str]:
    if not _which("wsl.exe"):
        return []
    try:
        result = subprocess.run(
            ["wsl.exe", "-l", "-q"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.strip().replace("\x00", "") for line in result.stdout.splitlines() if line.strip()]


def _git_bash_path() -> str | None:
    path_value = _which("bash.exe")
    if path_value:
        return path_value
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def list_profiles() -> list[TerminalProfile]:
    cwd = DEFAULT_CWD
    powershell_path = _which("powershell.exe") or "powershell.exe"
    cmd_path = _which("cmd.exe") or "cmd.exe"
    pwsh_path = _which("pwsh.exe")
    wsl_path = _which("wsl.exe")
    wsl_distros = _wsl_distros()
    git_bash_path = _git_bash_path()
    macos_target = os.environ.get("VELLUM_MACOS_SSH_TARGET", "").strip()

    return [
        TerminalProfile("powershell", "PowerShell", powershell_path, ["-NoLogo"], cwd, True),
        TerminalProfile("cmd", "CMD", cmd_path, [], cwd, True),
        TerminalProfile(
            "pwsh",
            "PowerShell Core",
            pwsh_path or "pwsh.exe",
            ["-NoLogo"],
            cwd,
            pwsh_path is not None,
            None if pwsh_path else "pwsh.exe was not found on PATH.",
        ),
        TerminalProfile(
            "wsl",
            "WSL Ubuntu",
            wsl_path or "wsl.exe",
            ["-d", "Ubuntu"],
            cwd,
            wsl_path is not None and "Ubuntu" in wsl_distros,
            None if wsl_path and "Ubuntu" in wsl_distros else "WSL Ubuntu is not available.",
        ),
        TerminalProfile(
            "git-bash",
            "Git Bash",
            git_bash_path or "bash.exe",
            ["--login"],
            cwd,
            git_bash_path is not None,
            None if git_bash_path else "Git Bash was not found.",
        ),
        TerminalProfile(
            "macos",
            "macOS SSH",
            "ssh",
            [macos_target] if macos_target else [],
            cwd,
            bool(macos_target),
            None if macos_target else "macOS SSH target is not configured. Set VELLUM_MACOS_SSH_TARGET.",
        ),
    ]


def get_profile(profile_id: str) -> TerminalProfile | None:
    canonical = PROFILE_ALIASES.get(profile_id.casefold())
    if not canonical:
        return None
    return next((profile for profile in list_profiles() if profile.id == canonical), None)
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```powershell
cd backend
python -m pytest tests/test_terminal_profiles.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/agent/terminal/__init__.py backend/agent/terminal/profiles.py backend/tests/test_terminal_profiles.py
git commit -m "Add terminal shell profile catalog"
```

---

### Task 2: Backend Terminal Session Lifecycle

**Files:**
- Create: `backend/agent/terminal/session.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/test_terminal_session.py`

- [ ] **Step 1: Write the failing session lifecycle tests**

Create `backend/tests/test_terminal_session.py`:

```python
import asyncio
from pathlib import Path

import pytest

from agent.terminal.profiles import TerminalProfile
from agent.terminal.session import TerminalSession, TerminalSessionManager


class FakeTransport:
    def __init__(self):
        self.started = False
        self.closed = False
        self.inputs = []
        self.resizes = []
        self.output = asyncio.Queue()
        self.returncode = None

    async def start(self):
        self.started = True
        await self.output.put("ready\r\n")

    async def read(self):
        return await self.output.get()

    async def write(self, data):
        self.inputs.append(data)

    async def resize(self, cols, rows):
        self.resizes.append((cols, rows))

    async def terminate(self):
        self.closed = True
        self.returncode = 0
        await self.output.put(None)


def make_profile():
    return TerminalProfile(
        id="powershell",
        label="PowerShell",
        command="powershell.exe",
        args=["-NoLogo"],
        cwd=Path("C:/work"),
        available=True,
    )


@pytest.mark.asyncio
async def test_terminal_session_starts_and_streams_output():
    transport = FakeTransport()
    session = TerminalSession("session-1", make_profile(), lambda profile: transport)

    await session.start()
    output = await asyncio.wait_for(session.read(), timeout=1)

    assert transport.started is True
    assert output == "ready\r\n"


@pytest.mark.asyncio
async def test_terminal_session_forwards_input_and_resize():
    transport = FakeTransport()
    session = TerminalSession("session-1", make_profile(), lambda profile: transport)

    await session.start()
    await session.write("Get-Location\r")
    await session.resize(120, 32)

    assert transport.inputs == ["Get-Location\r"]
    assert transport.resizes == [(120, 32)]


@pytest.mark.asyncio
async def test_terminal_session_terminate_closes_transport():
    transport = FakeTransport()
    session = TerminalSession("session-1", make_profile(), lambda profile: transport)

    await session.start()
    await session.terminate()

    assert transport.closed is True


@pytest.mark.asyncio
async def test_manager_creates_and_removes_sessions():
    transport = FakeTransport()
    manager = TerminalSessionManager(transport_factory=lambda profile: transport)

    session = await manager.create(make_profile())
    assert session.id in manager.sessions

    await manager.terminate(session.id)

    assert session.id not in manager.sessions
    assert transport.closed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd backend
python -m pytest tests/test_terminal_session.py -v
```

Expected: FAIL with `ModuleNotFoundError` or missing `TerminalSession`.

- [ ] **Step 3: Add Windows PTY dependency**

Modify `backend/pyproject.toml` dependencies by adding:

```toml
  "pywinpty>=2.0.13; platform_system == 'Windows'",
```

Place it near the other runtime dependencies, for example after `psutil>=6.0.0`.

- [ ] **Step 4: Implement terminal sessions and transports**

Create `backend/agent/terminal/session.py`:

```python
from __future__ import annotations

import asyncio
from collections.abc import Callable
import os
from pathlib import Path
import subprocess
import uuid

from agent.terminal.profiles import TerminalProfile


class TerminalTransport:
    async def start(self) -> None:
        raise NotImplementedError

    async def read(self) -> str | None:
        raise NotImplementedError

    async def write(self, data: str) -> None:
        raise NotImplementedError

    async def resize(self, cols: int, rows: int) -> None:
        raise NotImplementedError

    async def terminate(self) -> None:
        raise NotImplementedError


class SubprocessTerminalTransport(TerminalTransport):
    def __init__(self, profile: TerminalProfile):
        self.profile = profile
        self.process: subprocess.Popen[str] | None = None
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.process = subprocess.Popen(
            [self.profile.command, *self.profile.args],
            cwd=str(self.profile.cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())

    async def _read_stdout(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None
        loop = asyncio.get_running_loop()
        try:
            while True:
                line = await loop.run_in_executor(None, self.process.stdout.readline)
                if line == "":
                    break
                await self._queue.put(line)
        finally:
            await self._queue.put(None)

    async def read(self) -> str | None:
        return await self._queue.get()

    async def write(self, data: str) -> None:
        if self.process is None or self.process.stdin is None:
            return
        self.process.stdin.write(data)
        self.process.stdin.flush()

    async def resize(self, cols: int, rows: int) -> None:
        return None

    async def terminate(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(self.process.wait), timeout=2)
            except asyncio.TimeoutError:
                self.process.kill()
        if self._reader_task:
            self._reader_task.cancel()
```

Append the optional WinPTY factory and session manager in the same file:

```python
class WinPtyTerminalTransport(TerminalTransport):
    def __init__(self, profile: TerminalProfile, cols: int = 120, rows: int = 32):
        self.profile = profile
        self.cols = cols
        self.rows = rows
        self._process = None
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        from winpty import PtyProcess

        command_line = " ".join([self.profile.command, *self.profile.args])
        self._process = PtyProcess.spawn(command_line, cwd=str(self.profile.cwd), dimensions=(self.rows, self.cols))
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        assert self._process is not None
        while self._process.isalive():
            try:
                data = await asyncio.to_thread(self._process.read, 4096)
            except EOFError:
                break
            if data:
                await self._queue.put(data)
        await self._queue.put(None)

    async def read(self) -> str | None:
        return await self._queue.get()

    async def write(self, data: str) -> None:
        if self._process is not None and self._process.isalive():
            self._process.write(data)

    async def resize(self, cols: int, rows: int) -> None:
        self.cols = cols
        self.rows = rows
        if self._process is not None and self._process.isalive():
            self._process.set_size(rows, cols)

    async def terminate(self) -> None:
        if self._process is not None and self._process.isalive():
            self._process.terminate(force=True)
        if self._reader_task:
            self._reader_task.cancel()


def default_transport_factory(profile: TerminalProfile) -> TerminalTransport:
    if os.name == "nt":
        try:
            import winpty  # noqa: F401

            return WinPtyTerminalTransport(profile)
        except Exception:
            return SubprocessTerminalTransport(profile)
    return SubprocessTerminalTransport(profile)


class TerminalSession:
    def __init__(
        self,
        session_id: str,
        profile: TerminalProfile,
        transport_factory: Callable[[TerminalProfile], TerminalTransport] = default_transport_factory,
    ):
        self.id = session_id
        self.profile = profile
        self.transport = transport_factory(profile)
        self.started = False

    async def start(self) -> None:
        if self.started:
            return
        await self.transport.start()
        self.started = True

    async def read(self) -> str | None:
        return await self.transport.read()

    async def write(self, data: str) -> None:
        if not self.started:
            raise RuntimeError("terminal session is not ready")
        await self.transport.write(data)

    async def resize(self, cols: int, rows: int) -> None:
        if not self.started:
            return
        await self.transport.resize(cols, rows)

    async def terminate(self) -> None:
        await self.transport.terminate()


class TerminalSessionManager:
    def __init__(self, transport_factory: Callable[[TerminalProfile], TerminalTransport] = default_transport_factory):
        self.transport_factory = transport_factory
        self.sessions: dict[str, TerminalSession] = {}

    async def create(self, profile: TerminalProfile) -> TerminalSession:
        session = TerminalSession(str(uuid.uuid4()), profile, self.transport_factory)
        await session.start()
        self.sessions[session.id] = session
        return session

    def get(self, session_id: str) -> TerminalSession | None:
        return self.sessions.get(session_id)

    async def terminate(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session is not None:
            await session.terminate()
```

- [ ] **Step 5: Run session tests**

Run:

```powershell
cd backend
python -m pytest tests/test_terminal_session.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/pyproject.toml backend/agent/terminal/session.py backend/tests/test_terminal_session.py
git commit -m "Add terminal session lifecycle"
```

---

### Task 3: Backend Terminal API

**Files:**
- Modify: `backend/agent/api.py`
- Test: `backend/tests/test_terminal_api.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_terminal_api.py`:

```python
import asyncio

from fastapi.testclient import TestClient

from agent import api
from agent.terminal.profiles import TerminalProfile


class FakeSession:
    def __init__(self, profile):
        self.id = "session-test"
        self.profile = profile
        self.writes = []
        self.resizes = []
        self.reads = asyncio.Queue()
        self.reads.put_nowait("hello\r\n")
        self.reads.put_nowait(None)

    async def read(self):
        return await self.reads.get()

    async def write(self, data):
        self.writes.append(data)

    async def resize(self, cols, rows):
        self.resizes.append((cols, rows))

    async def terminate(self):
        return None


class FakeManager:
    def __init__(self):
        self.created = []
        self.terminated = []
        self.session = None

    async def create(self, profile):
        self.session = FakeSession(profile)
        self.created.append(profile.id)
        return self.session

    async def terminate(self, session_id):
        self.terminated.append(session_id)


def available_profile():
    return TerminalProfile("powershell", "PowerShell", "powershell.exe", ["-NoLogo"], api.Path("."), True)


def test_terminal_profiles_endpoint(monkeypatch):
    monkeypatch.setattr(api, "list_terminal_profiles", lambda: [available_profile()])

    with TestClient(api.app) as client:
        response = client.get("/api/terminal/profiles")

    assert response.status_code == 200
    assert response.json()["profiles"][0]["id"] == "powershell"


def test_terminal_websocket_starts_profile_and_streams_output(monkeypatch):
    fake_manager = FakeManager()
    monkeypatch.setattr(api, "terminal_session_manager", fake_manager)
    monkeypatch.setattr(api, "get_terminal_profile", lambda profile_id: available_profile())

    with TestClient(api.app) as client:
        with client.websocket_connect("/api/terminal/ws") as websocket:
            websocket.send_json({"type": "start", "profile": "powershell", "cols": 100, "rows": 30})
            assert websocket.receive_json() == {
                "type": "ready",
                "sessionId": "session-test",
                "profile": "powershell",
            }
            assert websocket.receive_json() == {"type": "output", "data": "hello\r\n"}

    assert fake_manager.created == ["powershell"]


def test_terminal_websocket_rejects_unknown_profile(monkeypatch):
    monkeypatch.setattr(api, "get_terminal_profile", lambda profile_id: None)

    with TestClient(api.app) as client:
        with client.websocket_connect("/api/terminal/ws") as websocket:
            websocket.send_json({"type": "start", "profile": "nope"})
            message = websocket.receive_json()

    assert message["type"] == "error"
    assert "Unknown terminal profile" in message["message"]


def test_terminal_websocket_rejects_unavailable_profile(monkeypatch):
    profile = TerminalProfile("macos", "macOS SSH", "ssh", [], api.Path("."), False, "not configured")
    monkeypatch.setattr(api, "get_terminal_profile", lambda profile_id: profile)

    with TestClient(api.app) as client:
        with client.websocket_connect("/api/terminal/ws") as websocket:
            websocket.send_json({"type": "start", "profile": "macos"})
            message = websocket.receive_json()

    assert message == {"type": "error", "message": "not configured"}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd backend
python -m pytest tests/test_terminal_api.py -v
```

Expected: FAIL because routes and API-level terminal objects do not exist.

- [ ] **Step 3: Add imports and terminal manager to `backend/agent/api.py`**

Add these imports near the other imports:

```python
from fastapi import WebSocket, WebSocketDisconnect
from agent.terminal.profiles import get_profile as get_terminal_profile
from agent.terminal.profiles import list_profiles as list_terminal_profiles
from agent.terminal.session import TerminalSessionManager
```

Add this module-level object near `_fts5_memory`:

```python
terminal_session_manager = TerminalSessionManager()
```

- [ ] **Step 4: Add terminal routes to `backend/agent/api.py`**

Add these route handlers before `app.include_router(router)`:

```python
@router.get("/terminal/profiles")
async def terminal_profiles() -> dict[str, list[dict[str, object]]]:
    return {"profiles": [profile.to_public_dict() for profile in list_terminal_profiles()]}


@router.websocket("/terminal/ws")
async def terminal_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    session = None
    output_task: asyncio.Task[None] | None = None

    async def pump_output() -> None:
        assert session is not None
        while True:
            data = await session.read()
            if data is None:
                await websocket.send_json({"type": "exit", "code": 0})
                break
            await websocket.send_json({"type": "output", "data": data})

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            if msg_type == "start":
                profile_id = str(message.get("profile") or "powershell")
                profile = get_terminal_profile(profile_id)
                if profile is None:
                    await websocket.send_json({"type": "error", "message": f"Unknown terminal profile: {profile_id}"})
                    continue
                if not profile.available:
                    await websocket.send_json({"type": "error", "message": profile.reason or f"{profile.label} is unavailable."})
                    continue
                session = await terminal_session_manager.create(profile)
                cols = int(message.get("cols") or 120)
                rows = int(message.get("rows") or 32)
                await session.resize(cols, rows)
                await websocket.send_json({"type": "ready", "sessionId": session.id, "profile": profile.id})
                output_task = asyncio.create_task(pump_output())
            elif msg_type == "input" and session is not None:
                await session.write(str(message.get("data") or ""))
            elif msg_type == "resize" and session is not None:
                await session.resize(int(message.get("cols") or 120), int(message.get("rows") or 32))
            elif msg_type == "terminate":
                break
            else:
                await websocket.send_json({"type": "error", "message": "Terminal session is not ready."})
    except WebSocketDisconnect:
        return
    finally:
        if output_task is not None:
            output_task.cancel()
        if session is not None:
            await terminal_session_manager.terminate(session.id)
```

- [ ] **Step 5: Run API tests**

Run:

```powershell
cd backend
python -m pytest tests/test_terminal_api.py -v
```

Expected: PASS.

- [ ] **Step 6: Run focused backend regression tests**

Run:

```powershell
cd backend
python -m pytest tests/test_terminal_profiles.py tests/test_terminal_session.py tests/test_terminal_api.py tests/test_api.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/agent/api.py backend/tests/test_terminal_api.py
git commit -m "Expose web terminal API"
```

---

### Task 4: Frontend Command Parser And Test Harness

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/ui/terminal/commands.js`
- Test: `frontend/ui/terminal/commands.test.js`

- [ ] **Step 1: Add test and terminal dependencies**

Modify `frontend/package.json`:

```json
{
  "name": "vellum-ui",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "start": "bash scripts/start-ui.sh",
    "stop": "bash scripts/stop.sh",
    "dev": "vite --host 127.0.0.1 --port 5173",
    "build": "vite build",
    "preview": "vite preview --host 127.0.0.1 --port 5173",
    "test": "vitest run --environment jsdom"
  },
  "dependencies": {
    "@vitejs/plugin-react": "^5.0.4",
    "@xterm/addon-fit": "^0.10.0",
    "@xterm/xterm": "^5.5.0",
    "vite": "^7.1.12",
    "react": "^19.1.1",
    "react-dom": "^19.1.1",
    "three": "^0.180.0"
  },
  "devDependencies": {
    "jsdom": "^25.0.1",
    "vitest": "^2.1.9"
  }
}
```

Run:

```powershell
cd frontend
npm install
```

Expected: `package-lock.json` updates with the new packages.

- [ ] **Step 2: Write failing parser tests**

Create `frontend/ui/terminal/commands.test.js`:

```javascript
import { describe, expect, test } from "vitest";
import { parseTerminalCommand } from "./commands.js";

describe("parseTerminalCommand", () => {
  test("passes ordinary shell input through", () => {
    expect(parseTerminalCommand("Get-Location")).toEqual({
      type: "shell",
      raw: "Get-Location",
    });
  });

  test("opens vellum mode for bare vellum", () => {
    expect(parseTerminalCommand("vellum")).toEqual({ type: "vellum" });
  });

  test("opens vellum mode for slash vellum", () => {
    expect(parseTerminalCommand("/vellum")).toEqual({ type: "vellum" });
  });

  test("parses shell switch commands", () => {
    expect(parseTerminalCommand("/shell cmd")).toEqual({
      type: "switch-shell",
      profile: "cmd",
    });
  });

  test("parses new tab commands", () => {
    expect(parseTerminalCommand("/new ubuntu")).toEqual({
      type: "new-tab",
      profile: "ubuntu",
    });
    expect(parseTerminalCommand("/new")).toEqual({
      type: "new-tab",
      profile: null,
    });
  });

  test("parses tabs and close commands", () => {
    expect(parseTerminalCommand("/tabs")).toEqual({ type: "tabs" });
    expect(parseTerminalCommand("/close")).toEqual({ type: "close-tab" });
  });

  test("reports unknown slash commands", () => {
    expect(parseTerminalCommand("/wat")).toEqual({
      type: "unknown",
      command: "/wat",
    });
  });
});
```

- [ ] **Step 3: Run parser tests to verify they fail**

Run:

```powershell
cd frontend
npm test -- ui/terminal/commands.test.js
```

Expected: FAIL because `commands.js` does not exist.

- [ ] **Step 4: Implement parser**

Create `frontend/ui/terminal/commands.js`:

```javascript
const SHELL_ALIASES = new Set([
  "powershell",
  "ps",
  "cmd",
  "pwsh",
  "ubuntu",
  "wsl",
  "bash",
  "git-bash",
  "mac",
  "macos",
]);

export function parseTerminalCommand(input) {
  const raw = String(input || "").trim();
  if (!raw) return { type: "empty" };
  if (raw === "vellum" || raw === "/vellum") return { type: "vellum" };
  if (!raw.startsWith("/")) return { type: "shell", raw };

  const [command, arg] = raw.slice(1).split(/\s+/, 2);
  if (command === "shell" && arg && SHELL_ALIASES.has(arg)) {
    return { type: "switch-shell", profile: arg };
  }
  if (command === "new") {
    return { type: "new-tab", profile: arg || null };
  }
  if (command === "tabs") return { type: "tabs" };
  if (command === "close") return { type: "close-tab" };
  return { type: "unknown", command: raw };
}
```

- [ ] **Step 5: Run parser tests**

Run:

```powershell
cd frontend
npm test -- ui/terminal/commands.test.js
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add frontend/package.json frontend/package-lock.json frontend/ui/terminal/commands.js frontend/ui/terminal/commands.test.js
git commit -m "Add terminal command parser"
```

---

### Task 5: Frontend Terminal Workspace Module

**Files:**
- Create: `frontend/ui/terminal/terminal-workspace.js`
- Test: `frontend/ui/terminal/terminal-workspace.test.js`

- [ ] **Step 1: Write failing workspace tests**

Create `frontend/ui/terminal/terminal-workspace.test.js`:

```javascript
import { beforeEach, describe, expect, test, vi } from "vitest";
import { createTerminalWorkspace } from "./terminal-workspace.js";

class FakeTerminal {
  constructor() {
    this.lines = [];
    this.handlers = [];
  }
  open() {}
  focus() {}
  write(data) {
    this.lines.push(data);
  }
  writeln(data) {
    this.lines.push(`${data}\r\n`);
  }
  onData(handler) {
    this.handlers.push(handler);
    return { dispose() {} };
  }
  emit(data) {
    this.handlers.forEach((handler) => handler(data));
  }
  dispose() {}
}

class FakeSocket {
  constructor() {
    this.sent = [];
    this.readyState = WebSocket.OPEN;
  }
  send(data) {
    this.sent.push(JSON.parse(data));
  }
  close() {}
}

describe("createTerminalWorkspace", () => {
  let root;
  let sockets;

  beforeEach(() => {
    root = document.createElement("div");
    document.body.innerHTML = "";
    document.body.appendChild(root);
    sockets = [];
  });

  test("mounts one default terminal tab", async () => {
    const workspace = createTerminalWorkspace(root, {
      TerminalClass: FakeTerminal,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    });

    await workspace.mount();

    expect(root.querySelector(".terminal-tab.active").textContent).toContain("PowerShell");
    expect(sockets[0].sent[0]).toMatchObject({ type: "start", profile: "powershell" });
  });

  test("plus button opens a new terminal tab", async () => {
    const workspace = createTerminalWorkspace(root, {
      TerminalClass: FakeTerminal,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    });

    await workspace.mount();
    root.querySelector("[data-terminal-new]").click();

    expect(root.querySelectorAll(".terminal-tab")).toHaveLength(2);
    expect(sockets).toHaveLength(2);
  });

  test("slash new creates a requested profile tab", async () => {
    const workspace = createTerminalWorkspace(root, {
      TerminalClass: FakeTerminal,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    });

    await workspace.mount();
    workspace.handleCommand("/new cmd");

    expect(sockets[1].sent[0]).toMatchObject({ type: "start", profile: "cmd" });
  });

  test("vellum command enters vellum mode without sending shell input", async () => {
    const onOpenVellum = vi.fn();
    const workspace = createTerminalWorkspace(root, {
      TerminalClass: FakeTerminal,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      onOpenVellum,
    });

    await workspace.mount();
    workspace.handleCommand("vellum");

    expect(onOpenVellum).toHaveBeenCalledOnce();
    expect(sockets[0].sent).toHaveLength(1);
  });

  test("unknown slash commands print terminal output", async () => {
    const workspace = createTerminalWorkspace(root, {
      TerminalClass: FakeTerminal,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    });

    await workspace.mount();
    workspace.handleCommand("/unknown");

    expect(workspace.activeTerminal.lines.join("")).toContain("unknown command");
  });
});
```

- [ ] **Step 2: Run workspace tests to verify they fail**

Run:

```powershell
cd frontend
npm test -- ui/terminal/terminal-workspace.test.js
```

Expected: FAIL because `terminal-workspace.js` does not exist.

- [ ] **Step 3: Implement workspace module**

Create `frontend/ui/terminal/terminal-workspace.js`:

```javascript
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { parseTerminalCommand } from "./commands.js";

const DEFAULT_PROFILES = [
  { id: "powershell", label: "PowerShell", available: true },
  { id: "cmd", label: "CMD", available: true },
  { id: "pwsh", label: "PowerShell Core", available: false },
  { id: "wsl", label: "WSL Ubuntu", available: false },
  { id: "git-bash", label: "Git Bash", available: false },
  { id: "macos", label: "macOS SSH", available: false },
];

function wsUrl() {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/api/terminal/ws`;
}

export function createTerminalWorkspace(root, options = {}) {
  const TerminalClass = options.TerminalClass || XTerm;
  const socketFactory = options.socketFactory || (() => new WebSocket(wsUrl()));
  const onOpenVellum = options.onOpenVellum || (() => {});
  const profiles = options.profiles || DEFAULT_PROFILES;
  const tabs = [];
  let activeTab = null;
  let tabCounter = 0;

  function renderShell() {
    root.innerHTML = `
      <div class="terminal-workspace">
        <div class="terminal-toolbar">
          <div class="terminal-tabs" data-terminal-tabs></div>
          <button class="terminal-new" type="button" data-terminal-new title="New terminal">+</button>
          <select class="terminal-shell-select" data-terminal-shell></select>
        </div>
        <div class="terminal-stage" data-terminal-stage></div>
        <div class="terminal-status" data-terminal-status>disconnected</div>
      </div>
    `;
    const select = root.querySelector("[data-terminal-shell]");
    select.innerHTML = profiles.map((profile) => (
      `<option value="${profile.id}" ${profile.available === false ? "disabled" : ""}>${profile.label}</option>`
    )).join("");
    root.querySelector("[data-terminal-new]").addEventListener("click", () => newTab());
    select.addEventListener("change", () => switchShell(select.value));
  }

  function renderTabs() {
    const tabHost = root.querySelector("[data-terminal-tabs]");
    tabHost.innerHTML = tabs.map((tab) => `
      <button class="terminal-tab ${tab === activeTab ? "active" : ""}" data-tab-id="${tab.id}" type="button">
        <span>${tab.title}</span>
        <span class="terminal-tab-close" data-close-tab="${tab.id}">x</span>
      </button>
    `).join("");
    tabHost.querySelectorAll("[data-tab-id]").forEach((button) => {
      button.addEventListener("click", (event) => {
        if (event.target.matches("[data-close-tab]")) return;
        activateTab(button.dataset.tabId);
      });
    });
    tabHost.querySelectorAll("[data-close-tab]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        closeTab(button.dataset.closeTab);
      });
    });
  }

  function renderStatus(text) {
    root.querySelector("[data-terminal-status]").textContent = text;
  }

  function activeProfileLabel(profileId) {
    return profiles.find((profile) => profile.id === profileId)?.label || profileId;
  }

  function makeTerminal() {
    const terminal = new TerminalClass({
      cursorBlink: true,
      fontFamily: "JetBrains Mono, Consolas, monospace",
      fontSize: 13,
      theme: { background: "#050505", foreground: "#f4f4f4" },
    });
    return terminal;
  }

  function attachSocket(tab) {
    tab.socket = socketFactory(tab.profile);
    tab.socket.onopen = () => {
      tab.socket.send(JSON.stringify({ type: "start", profile: tab.profile, cols: 120, rows: 32 }));
      renderStatus(`${activeProfileLabel(tab.profile)} · connecting`);
    };
    tab.socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "ready") renderStatus(`${activeProfileLabel(tab.profile)} · ready`);
      if (message.type === "output") tab.terminal.write(message.data);
      if (message.type === "error") tab.terminal.writeln(`\r\n${message.message}`);
      if (message.type === "exit") renderStatus(`${activeProfileLabel(tab.profile)} · exited`);
    };
    if (tab.socket.readyState === WebSocket.OPEN) {
      tab.socket.send(JSON.stringify({ type: "start", profile: tab.profile, cols: 120, rows: 32 }));
    }
  }

  function newTab(profile = "powershell") {
    const terminal = makeTerminal();
    const tab = {
      id: `term-${++tabCounter}`,
      title: activeProfileLabel(profile),
      profile,
      inputBuffer: "",
      terminal,
      socket: null,
      fit: typeof FitAddon === "function" ? new FitAddon() : null,
    };
    tabs.push(tab);
    activeTab = tab;
    renderTabs();
    mountActiveTerminal();
    attachSocket(tab);
    return tab;
  }

  function mountActiveTerminal() {
    const stage = root.querySelector("[data-terminal-stage]");
    stage.innerHTML = "";
    if (!activeTab) return;
    const host = document.createElement("div");
    host.className = "terminal-host";
    stage.appendChild(host);
    if (activeTab.fit && activeTab.terminal.loadAddon) activeTab.terminal.loadAddon(activeTab.fit);
    activeTab.terminal.open(host);
    if (activeTab.fit) activeTab.fit.fit();
    activeTab.terminal.onData((data) => {
      if (data === "\r") {
        activeTab.terminal.write("\r\n");
        handleCommand(activeTab.inputBuffer);
        activeTab.inputBuffer = "";
        return;
      }
      if (data === "\u007f") {
        if (activeTab.inputBuffer.length > 0) {
          activeTab.inputBuffer = activeTab.inputBuffer.slice(0, -1);
          activeTab.terminal.write("\b \b");
        }
        return;
      }
      activeTab.inputBuffer += data;
      activeTab.terminal.write(data);
    });
    activeTab.terminal.focus();
    root.querySelector("[data-terminal-shell]").value = activeTab.profile;
    renderStatus(`${activeProfileLabel(activeTab.profile)} · active`);
  }

  function activateTab(id) {
    activeTab = tabs.find((tab) => tab.id === id) || activeTab;
    renderTabs();
    mountActiveTerminal();
  }

  function closeTab(id = activeTab?.id, replaceWhenEmpty = true) {
    const index = tabs.findIndex((tab) => tab.id === id);
    if (index === -1) return;
    const [tab] = tabs.splice(index, 1);
    if (tab.socket) {
      tab.socket.send(JSON.stringify({ type: "terminate" }));
      tab.socket.close();
    }
    tab.terminal.dispose();
    activeTab = tabs[index] || tabs[index - 1] || null;
    if (!activeTab && replaceWhenEmpty) newTab();
    else {
      renderTabs();
      mountActiveTerminal();
    }
  }

  function switchShell(profile) {
    if (!activeTab) return;
    closeTab(activeTab.id, false);
    newTab(profile);
  }

  function handleCommand(input) {
    const parsed = parseTerminalCommand(input);
    if (parsed.type === "empty") return;
    if (parsed.type === "shell") {
      activeTab?.socket?.send(JSON.stringify({ type: "input", data: `${parsed.raw}\r` }));
      return;
    }
    if (parsed.type === "vellum") {
      if (activeTab) activeTab.title = "vellum";
      renderTabs();
      onOpenVellum({ tab: activeTab });
      return;
    }
    if (parsed.type === "new-tab") {
      newTab(parsed.profile || "powershell");
      return;
    }
    if (parsed.type === "switch-shell") {
      switchShell(parsed.profile);
      return;
    }
    if (parsed.type === "tabs") {
      activeTab?.terminal.writeln(tabs.map((tab, index) => `${index + 1}. ${tab.title}`).join("\r\n"));
      return;
    }
    if (parsed.type === "close-tab") {
      closeTab();
      return;
    }
    activeTab?.terminal.writeln(`unknown command: ${parsed.command}`);
  }

  async function mount() {
    renderShell();
    newTab("powershell");
  }

  return {
    mount,
    newTab,
    handleCommand,
    get activeTerminal() {
      return activeTab?.terminal;
    },
  };
}
```

- [ ] **Step 4: Run workspace tests**

Run:

```powershell
cd frontend
npm test -- ui/terminal/terminal-workspace.test.js
```

Expected: PASS. If tests fail because `WebSocket.OPEN` is undefined in jsdom, set `global.WebSocket = { OPEN: 1 }` in `beforeEach`.

- [ ] **Step 5: Run frontend parser and workspace tests**

Run:

```powershell
cd frontend
npm test -- ui/terminal
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add frontend/ui/terminal/terminal-workspace.js frontend/ui/terminal/terminal-workspace.test.js
git commit -m "Add terminal workspace module"
```

---

### Task 6: Integrate Terminal Surface Into Existing Web UI

**Files:**
- Modify: `frontend/ui/vellum-chat.html`

- [ ] **Step 1: Add terminal surface markup**

In `frontend/ui/vellum-chat.html`, inside `<main class="stage">` after the existing `chatSurface` section, add:

```html
        <section class="surface hidden" id="terminalSurface">
          <div id="terminalMount" class="terminal-mount"></div>
        </section>
```

- [ ] **Step 2: Add terminal sidebar item**

Inside `<aside class="threads-rail" id="threadsRail">`, before the thread sections, add:

```html
        <div class="threads-section">
          <div class="threads-section-label">Workspace</div>
          <div class="thread-item" id="terminalNav">
            <span class="thread-num">›_</span>
            <span class="thread-title">Terminal</span>
          </div>
        </div>
```

- [ ] **Step 3: Add terminal styles**

In the `<style>` block after `.surface.hidden`, add:

```css
  .terminal-mount {
    flex: 1;
    min-height: 0;
    background: #050505;
    color: #f4f4f4;
    font-family: "JetBrains Mono", Consolas, monospace;
    overflow: hidden;
  }
  .terminal-workspace {
    height: 100%;
    display: grid;
    grid-template-rows: 38px 1fr 24px;
    background: #050505;
  }
  .terminal-toolbar {
    display: grid;
    grid-template-columns: 1fr 34px 180px;
    align-items: stretch;
    border-bottom: 1px solid rgba(255,255,255,0.12);
    background: #0d0d0d;
  }
  .terminal-tabs {
    display: flex;
    min-width: 0;
    overflow-x: auto;
  }
  .terminal-tab,
  .terminal-new,
  .terminal-shell-select {
    background: transparent;
    border: 0;
    border-right: 1px solid rgba(255,255,255,0.12);
    color: rgba(244,244,244,0.78);
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 12px;
  }
  .terminal-tab {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    min-width: 132px;
    padding: 0 12px;
    cursor: pointer;
  }
  .terminal-tab.active {
    color: #ffffff;
    background: rgba(255,255,255,0.06);
    border-bottom: 1px solid var(--ember);
  }
  .terminal-tab-close {
    margin-left: auto;
    color: rgba(244,244,244,0.46);
  }
  .terminal-new {
    cursor: pointer;
    font-size: 18px;
  }
  .terminal-shell-select {
    padding: 0 10px;
    outline: none;
  }
  .terminal-stage {
    min-height: 0;
    overflow: hidden;
  }
  .terminal-host {
    height: 100%;
    padding: 10px;
  }
  .terminal-status {
    border-top: 1px solid rgba(255,255,255,0.12);
    color: rgba(244,244,244,0.52);
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 11px;
    line-height: 24px;
    padding: 0 10px;
    background: #080808;
  }
```

- [ ] **Step 4: Wire terminal state in the existing script**

In the script variable block near `const threadsRail = $('threadsRail');`, add:

```javascript
  const terminalSurface = $('terminalSurface');
  const terminalMount = $('terminalMount');
  const terminalNav = $('terminalNav');
  let terminalWorkspace = null;
```

Add this helper near `showChat()`:

```javascript
  function showTerminal() {
    if (emptySurface) emptySurface.classList.add('hidden');
    if (chatSurface) chatSurface.classList.add('hidden');
    if (terminalSurface) terminalSurface.classList.remove('hidden');
    document.querySelectorAll('.thread-item').forEach(item => item.classList.remove('active'));
    if (terminalNav) terminalNav.classList.add('active');
    threadTitle.textContent = 'Terminal';
    threadMeta.textContent = 'multi-shell';
    if (!terminalWorkspace) {
      import('./terminal/terminal-workspace.js').then(mod => {
        terminalWorkspace = mod.createTerminalWorkspace(terminalMount, {
          onOpenVellum: openVellumTerminalMode,
        });
        terminalWorkspace.mount();
      }).catch(err => {
        terminalMount.textContent = `terminal failed to load: ${err.message || err}`;
      });
    }
  }
```

Add this helper after `showTerminal()`:

```javascript
  function openVellumTerminalMode() {
    terminalMount.innerHTML = '<iframe class="terminal-vellum-frame" title="Vellum terminal UI" src="/terminal/vellum/index.html"></iframe>';
  }
```

Add the iframe style next to terminal styles:

```css
  .terminal-vellum-frame {
    width: 100%;
    height: 100%;
    border: 0;
    background: #050505;
  }
```

Register the click handler near other rail handlers:

```javascript
  terminalNav.addEventListener('click', () => {
    showTerminal();
    closeRail();
  });
```

- [ ] **Step 5: Build to catch integration errors**

Run:

```powershell
cd frontend
npm run build
```

Expected: PASS and `ui-dist` generated.

- [ ] **Step 6: Commit**

```powershell
git add frontend/ui/vellum-chat.html
git commit -m "Add terminal surface to web UI"
```

---

### Task 7: Serve Vellum Terminal UI Mode

**Files:**
- Create: `frontend/ui/terminal/vellum/index.html`
- Copy/Create: `frontend/ui/terminal/vellum/themes.css`
- Copy/Create: `frontend/ui/terminal/vellum/setup/*`
- Modify: `frontend/vite.config.mjs`

- [ ] **Step 1: Copy the existing standalone TUI assets**

Copy these files from `../Vellum TUI` into `frontend/ui/terminal/vellum/`:

```text
Vellum TUI/index.html -> frontend/ui/terminal/vellum/index.html
Vellum TUI/themes.css -> frontend/ui/terminal/vellum/themes.css
Vellum TUI/setup/** -> frontend/ui/terminal/vellum/setup/**
```

Do not edit the source files under `Vellum TUI` in this task.

- [ ] **Step 2: Adjust API base in copied `index.html`**

In `frontend/ui/terminal/vellum/index.html`, keep:

```javascript
window.__VELLUM_API_BASE = location.origin;
```

This makes the iframe reuse the current FastAPI/Vite origin.

- [ ] **Step 3: Add Vite input for the iframe asset**

Modify `frontend/vite.config.mjs` rollup input:

```javascript
rollupOptions: {
  input: {
    app: 'ui/vellum-chat.html',
    terminalVellum: 'ui/terminal/vellum/index.html',
  },
},
```

- [ ] **Step 4: Build to verify copied assets resolve**

Run:

```powershell
cd frontend
npm run build
```

Expected: PASS. If Vite rejects the copied Babel CDN scripts, keep them as normal script tags and ensure relative `setup/*.jsx` files resolve from `ui/terminal/vellum/`.

- [ ] **Step 5: Commit**

```powershell
git add frontend/vite.config.mjs frontend/ui/terminal/vellum
git commit -m "Serve Vellum terminal UI mode"
```

---

### Task 8: End-To-End Verification

**Files:**
- No source changes expected unless verification finds a defect.

- [ ] **Step 1: Run backend focused tests**

Run:

```powershell
cd backend
python -m pytest tests/test_terminal_profiles.py tests/test_terminal_session.py tests/test_terminal_api.py tests/test_api.py -v
```

Expected: PASS.

- [ ] **Step 2: Run frontend tests**

Run:

```powershell
cd frontend
npm test -- ui/terminal
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
cd frontend
npm run build
```

Expected: PASS.

- [ ] **Step 4: Start backend and frontend**

Use the repo’s normal backend start command if documented. If not, from `backend` run:

```powershell
python -m uvicorn agent.api:app --host 127.0.0.1 --port 4242
```

From `frontend` run:

```powershell
npm run dev
```

Expected: backend on `http://127.0.0.1:4242`, frontend on `http://127.0.0.1:5173`.

- [ ] **Step 5: Manually verify terminal behavior**

Open `http://127.0.0.1:5173/` and verify:

```text
1. Click Terminal in the sidebar.
2. Confirm a black terminal opens.
3. Confirm one PowerShell tab exists.
4. Click + and confirm a second terminal tab opens.
5. Type /new cmd and confirm a CMD tab opens.
6. Type /shell powershell and confirm the active tab becomes PowerShell.
7. Type Get-Location in PowerShell and confirm output returns.
8. Type cmd /c echo hello in PowerShell and confirm hello prints.
9. Type /shell ubuntu and confirm WSL either opens or prints an unavailable message.
10. Type /shell mac and confirm macOS SSH prints disabled message unless VELLUM_MACOS_SSH_TARGET is configured.
11. Type vellum and confirm the Vellum terminal UI opens inside the terminal workspace.
```

- [ ] **Step 6: Commit verification fixes if needed**

Only if source fixes were required:

```powershell
git add backend frontend
git commit -m "Fix terminal verification issues"
```

---

## Self-Review Notes

- Spec coverage: The plan covers sidebar entry, black terminal workspace, multi-tab sessions, shell profile catalog, slash commands, `vellum` interception, disabled macOS profile, backend WebSocket transport, and test/verification steps.
- First implementation boundary: True local macOS command execution is explicitly excluded; macOS uses SSH only.
- Testing: Backend uses pytest. Frontend adds Vitest because the current frontend has no test harness.
- Risk: `pywinpty` behavior on the local Windows environment may need small adjustments. The session abstraction keeps those adjustments in `backend/agent/terminal/session.py`.
