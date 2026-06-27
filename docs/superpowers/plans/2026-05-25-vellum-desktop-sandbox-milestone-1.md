# Vellum Desktop Sandbox Milestone 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first visible computer-use milestone: a Tauri desktop shell with a whole-screen orange overlay and a backend workspace action bridge that can open browser, navigate, click, type, scroll, run terminal commands, and emit live events.

**Architecture:** Keep FastAPI as the agent brain. Add a backend `computer_use_workspace` action protocol behind the existing `computer_use` tool, then add a Tauri shell that loads the existing Web UI and controls a native overlay. Milestone 1 uses a controlled local workspace bridge, not Docker and not a claimed VM sandbox.

**Tech Stack:** FastAPI, LangChain tools, Playwright MCP, existing terminal subprocess support, Vite static UI, Tauri v2, Rust, WebView2 on Windows.

**Primary References:** Tauri v2 prerequisites document that Windows development requires Microsoft C++ Build Tools, WebView2, and Rust; Tauri v2 configuration supports `devUrl`, `frontendDist`, and `beforeDevCommand`; Tauri v2 exposes frontend-to-Rust commands through `invoke` and runtime capabilities.

---

## File Structure

Create:

- `backend/agent/computer_use_workspace.py` — semantic workspace action protocol and local worker implementation.
- `backend/tests/test_computer_use_workspace.py` — deterministic fake-worker tests.
- `desktop/package.json` — Tauri shell package scripts.
- `desktop/vite.config.mjs` — desktop shell Vite config on a stable Tauri dev port.
- `desktop/index.html` — minimal desktop shell page.
- `desktop/overlay.html` — transparent native overlay content.
- `desktop/src/main.js` — desktop shell JS bridge.
- `desktop/src/styles.css` — native shell UI and overlay page styles.
- `desktop/src-tauri/Cargo.toml` — Tauri Rust package.
- `desktop/src-tauri/tauri.conf.json` — Tauri app config.
- `desktop/src-tauri/capabilities/default.json` — Tauri command permissions.
- `desktop/src-tauri/src/main.rs` — Rust entrypoint.
- `desktop/src-tauri/src/lib.rs` — Tauri commands for backend health and overlay control.
- `scripts/start-desktop.ps1` — start Tauri desktop dev shell.

Modify:

- `backend/agent/api.py` — add workspace action/status endpoints.
- `backend/agent/tools/computer_use.py` — add `mode="workspace"` routing.
- `backend/agent/graph/agent.py` — teach the agent to use workspace mode for visible computer-use tasks.
- `backend/tests/test_api.py` — test workspace endpoints.
- `backend/tests/test_computer_use.py` — test `computer_use(mode="workspace")`.
- `frontend/ui/vellum-chat.html` — show workspace status/action events from backend.
- `frontend/ui/vellum-chat-voice.test.js` — assert workspace event wiring remains present.
- `package`/scripts only if needed to make desktop startup ergonomic.

Do not modify:

- Memory/Obsidian learning for action sessions. That belongs to Milestone 3.
- Always-listening voice. That belongs to Milestone 2.
- Docker or VM integrations. Docker is explicitly out of scope.

---

## Task 1: Backend Workspace Action Protocol

**Files:**
- Create: `backend/agent/computer_use_workspace.py`
- Create: `backend/tests/test_computer_use_workspace.py`

- [ ] **Step 1: Write failing tests for semantic workspace actions**

Add `backend/tests/test_computer_use_workspace.py`:

```python
from pathlib import Path

from agent.computer_use_workspace import LocalWorkspaceWorker, WorkspaceActionError


class FakePlaywright:
    def __init__(self):
        self.calls = []

    def __call__(self, params):
        self.calls.append(params)
        return f"browser:{params['action']}"


class FakeCommandRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, cwd):
        self.calls.append((command, cwd))
        return {"returncode": 0, "stdout": "ok", "stderr": ""}


def test_workspace_maps_browser_actions_to_playwright(tmp_path):
    browser = FakePlaywright()
    worker = LocalWorkspaceWorker(playwright_runner=browser, command_runner=FakeCommandRunner(), cwd=tmp_path)

    result = worker.run({"action": "browser.navigate", "url": "https://example.com"})

    assert result.status == "ok"
    assert result.action == "browser.navigate"
    assert browser.calls == [{"action": "navigate", "url": "https://example.com"}]
    assert "browser:navigate" in result.message


def test_workspace_maps_click_type_scroll_and_screenshot(tmp_path):
    browser = FakePlaywright()
    worker = LocalWorkspaceWorker(playwright_runner=browser, command_runner=FakeCommandRunner(), cwd=tmp_path)

    worker.run({"action": "input.click", "target": "button[name=Search]", "element": "Search"})
    worker.run({"action": "input.type", "target": "input[name=q]", "text": "vellum", "submit": True})
    worker.run({"action": "input.scroll", "amount": 2})
    worker.run({"action": "screen.screenshot", "filename": "workspace.png"})

    assert browser.calls == [
        {"action": "click", "target": "button[name=Search]", "element": "Search"},
        {"action": "type", "target": "input[name=q]", "text": "vellum", "submit": True},
        {"action": "press_key", "key": "PageDown"},
        {"action": "press_key", "key": "PageDown"},
        {"action": "screenshot", "filename": "workspace.png", "full_page": True},
    ]


def test_workspace_terminal_run_uses_controlled_cwd(tmp_path):
    commands = FakeCommandRunner()
    worker = LocalWorkspaceWorker(playwright_runner=FakePlaywright(), command_runner=commands, cwd=tmp_path)

    result = worker.run({"action": "terminal.run", "command": "echo hello"})

    assert result.status == "ok"
    assert commands.calls == [("echo hello", tmp_path)]
    assert result.data["returncode"] == 0
    assert result.data["stdout"] == "ok"


def test_workspace_rejects_unknown_or_missing_inputs(tmp_path):
    worker = LocalWorkspaceWorker(playwright_runner=FakePlaywright(), command_runner=FakeCommandRunner(), cwd=tmp_path)

    try:
        worker.run({"action": "browser.navigate"})
    except WorkspaceActionError as exc:
        assert "requires url" in str(exc)
    else:
        raise AssertionError("missing url should fail")

    try:
        worker.run({"action": "host.delete_files"})
    except WorkspaceActionError as exc:
        assert "Unsupported workspace action" in str(exc)
    else:
        raise AssertionError("unknown action should fail")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_computer_use_workspace.py -q
```

Expected: fail because `agent.computer_use_workspace` does not exist.

- [ ] **Step 3: Implement workspace worker**

Create `backend/agent/computer_use_workspace.py`:

```python
"""Controlled workspace action protocol for computer-use mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import Any, Callable

from agent.mcp.playwright_tools import run_tool as playwright_run


class WorkspaceActionError(ValueError):
    """Raised when a workspace action cannot be executed safely."""


@dataclass(frozen=True)
class WorkspaceActionResult:
    action: str
    status: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


def _default_command_runner(command: str, cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-8000:],
    }


class LocalWorkspaceWorker:
    """First controlled workspace worker.

    This is not a VM sandbox. It is a visible local workspace bridge that keeps
    browser and command actions behind a narrow protocol so a stronger worker
    can replace it later.
    """

    def __init__(
        self,
        *,
        playwright_runner: Callable[[dict[str, Any]], str] = playwright_run,
        command_runner: Callable[[str, Path], dict[str, Any]] = _default_command_runner,
        cwd: Path | None = None,
    ) -> None:
        self.playwright_runner = playwright_runner
        self.command_runner = command_runner
        self.cwd = cwd or Path(__file__).resolve().parents[2]

    def run(self, params: dict[str, Any]) -> WorkspaceActionResult:
        action = _action(params)
        if action == "browser.open":
            return self._browser_open(params)
        if action == "browser.navigate":
            return self._browser_navigate(params)
        if action == "input.click":
            return self._input_click(params)
        if action == "input.type":
            return self._input_type(params)
        if action == "input.scroll":
            return self._input_scroll(params)
        if action == "screen.screenshot":
            return self._screenshot(params)
        if action == "terminal.open":
            return WorkspaceActionResult(action, "ok", "Workspace terminal is available in the Vellum terminal panel.")
        if action == "terminal.run":
            return self._terminal_run(params)
        if action == "session.stop":
            return WorkspaceActionResult(action, "ok", "Workspace stop requested.")
        raise WorkspaceActionError(f"Unsupported workspace action: {action}")

    def _browser_open(self, params: dict[str, Any]) -> WorkspaceActionResult:
        url = str(params.get("url") or "about:blank").strip()
        message = self.playwright_runner({"action": "tabs", "tab_action": "new", "url": url})
        return WorkspaceActionResult("browser.open", "ok", message, {"url": url})

    def _browser_navigate(self, params: dict[str, Any]) -> WorkspaceActionResult:
        url = _required(params, "url", "browser.navigate requires url")
        message = self.playwright_runner({"action": "navigate", "url": url})
        return WorkspaceActionResult("browser.navigate", "ok", message, {"url": url})

    def _input_click(self, params: dict[str, Any]) -> WorkspaceActionResult:
        target = _required(params, "target", "input.click requires target")
        call = {"action": "click", "target": target}
        if params.get("element"):
            call["element"] = str(params["element"])
        message = self.playwright_runner(call)
        return WorkspaceActionResult("input.click", "ok", message, {"target": target})

    def _input_type(self, params: dict[str, Any]) -> WorkspaceActionResult:
        target = _required(params, "target", "input.type requires target")
        text = _required(params, "text", "input.type requires text")
        call: dict[str, Any] = {"action": "type", "target": target, "text": text}
        if params.get("element"):
            call["element"] = str(params["element"])
        if params.get("submit") is not None:
            call["submit"] = bool(params["submit"])
        message = self.playwright_runner(call)
        return WorkspaceActionResult("input.type", "ok", message, {"target": target, "text": "[redacted]"})

    def _input_scroll(self, params: dict[str, Any]) -> WorkspaceActionResult:
        amount = int(params.get("amount") or 1)
        key = "PageDown" if amount >= 0 else "PageUp"
        for _ in range(max(1, abs(amount))):
            self.playwright_runner({"action": "press_key", "key": key})
        return WorkspaceActionResult("input.scroll", "ok", f"Workspace scrolled with {key}.", {"amount": amount})

    def _screenshot(self, params: dict[str, Any]) -> WorkspaceActionResult:
        filename = str(params.get("filename") or "workspace.png")
        message = self.playwright_runner({"action": "screenshot", "filename": filename, "full_page": True})
        return WorkspaceActionResult("screen.screenshot", "ok", message, {"filename": filename})

    def _terminal_run(self, params: dict[str, Any]) -> WorkspaceActionResult:
        command = _required(params, "command", "terminal.run requires command")
        result = self.command_runner(command, self.cwd)
        status = "ok" if result.get("returncode") == 0 else "error"
        return WorkspaceActionResult(
            "terminal.run",
            status,
            f"Workspace command exited with {result.get('returncode')}.",
            result,
        )


def _action(params: dict[str, Any]) -> str:
    return str(params.get("action") or "").strip().casefold().replace("_", ".")


def _required(params: dict[str, Any], key: str, message: str) -> str:
    value = str(params.get(key) or "").strip()
    if not value:
        raise WorkspaceActionError(message)
    return value


workspace_worker = LocalWorkspaceWorker()
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_computer_use_workspace.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/agent/computer_use_workspace.py backend/tests/test_computer_use_workspace.py
git commit -m "feat: add computer-use workspace action protocol"
```

---

## Task 2: Backend Workspace API

**Files:**
- Modify: `backend/agent/api.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Append to `backend/tests/test_api.py`:

```python
def test_computer_use_workspace_action_records_event(monkeypatch):
    calls = []

    class FakeWorker:
        def run(self, params):
            calls.append(params)
            return api.WorkspaceActionResult(
                action=params["action"],
                status="ok",
                message="workspace-ok",
                data={"seen": True},
            )

    monkeypatch.setattr(api, "workspace_worker", FakeWorker())

    with TestClient(api.app) as client:
        response = client.post(
            "/api/computer-use/workspace/action",
            json={"action": "browser.navigate", "url": "https://example.com"},
        )

    assert response.status_code == 200
    body = response.json()
    assert calls == [{"action": "browser.navigate", "url": "https://example.com"}]
    assert body["status"] == "ok"
    assert body["message"] == "workspace-ok"
    assert body["data"] == {"seen": True}


def test_computer_use_workspace_action_returns_400_for_invalid_action(monkeypatch):
    class FakeWorker:
        def run(self, params):
            raise api.WorkspaceActionError("bad workspace action")

    monkeypatch.setattr(api, "workspace_worker", FakeWorker())

    with TestClient(api.app) as client:
        response = client.post("/api/computer-use/workspace/action", json={"action": "wat"})

    assert response.status_code == 400
    assert response.json()["detail"] == "bad workspace action"
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_api.py -k workspace_action -q
```

Expected: fail because the endpoint and imports do not exist.

- [ ] **Step 3: Add request model and endpoint**

In `backend/agent/api.py`, add imports near other local imports:

```python
from agent.computer_use_workspace import WorkspaceActionError, WorkspaceActionResult, workspace_worker
```

Add request model near `ComputerUseModeRequest`:

```python
class WorkspaceActionRequest(BaseModel):
    action: str = Field(min_length=1)
    url: str | None = None
    target: str | None = None
    element: str | None = None
    text: str | None = None
    command: str | None = None
    filename: str | None = None
    amount: int | None = None
    submit: bool | None = None
```

Add helper:

```python
def _workspace_action_payload(request: WorkspaceActionRequest) -> dict[str, Any]:
    return {key: value for key, value in request.model_dump().items() if value is not None}
```

Add endpoint near other `/computer-use/*` endpoints:

```python
@router.post("/computer-use/workspace/action")
async def computer_use_workspace_action(request: WorkspaceActionRequest) -> dict[str, Any]:
    params = _workspace_action_payload(request)
    try:
        result = await asyncio.to_thread(workspace_worker.run, params)
    except WorkspaceActionError as exc:
        computer_use_runtime.record_event(
            "workspace_error",
            str(exc),
            tool="computer_use_workspace",
            data={"action": request.action},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    computer_use_runtime.record_event(
        "workspace_action",
        result.message,
        tool="computer_use_workspace",
        data={
            "action": result.action,
            "status": result.status,
            "result": result.data,
        },
    )
    return {
        "action": result.action,
        "status": result.status,
        "message": result.message,
        "data": result.data,
    }
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_api.py -k workspace_action -q
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/agent/api.py backend/tests/test_api.py
git commit -m "feat: expose computer-use workspace action API"
```

---

## Task 3: Route Agent Tool Calls To Workspace Mode

**Files:**
- Modify: `backend/agent/tools/computer_use.py`
- Modify: `backend/agent/graph/agent.py`
- Modify: `backend/tests/test_computer_use.py`
- Modify: `backend/tests/test_agent_prompt.py`

- [ ] **Step 1: Write failing tool routing test**

Append to `backend/tests/test_computer_use.py`:

```python
def test_computer_use_routes_workspace_actions(monkeypatch):
    calls = []

    class FakeResult:
        action = "browser.navigate"
        status = "ok"
        message = "workspace-ok"
        data = {"url": "https://example.com"}

    class FakeWorker:
        def run(self, params):
            calls.append(params)
            return FakeResult()

    monkeypatch.setattr(computer_use_tools, "workspace_worker", FakeWorker())

    result = computer_use_tools.computer_use.invoke(
        {"mode": "workspace", "action": "browser.navigate", "url": "https://example.com"}
    )

    assert result == "workspace-ok"
    assert calls == [{"action": "browser.navigate", "url": "https://example.com"}]
```

Append to `backend/tests/test_agent_prompt.py`:

```python
def test_agent_prompt_documents_workspace_mode():
    from agent.graph.agent import VELLUM_SYSTEM_PROMPT

    assert "mode='workspace'" in VELLUM_SYSTEM_PROMPT
    assert "visible workspace" in VELLUM_SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_computer_use.py::test_computer_use_routes_workspace_actions backend/tests/test_agent_prompt.py::test_agent_prompt_documents_workspace_mode -q
```

Expected: fail because `mode="workspace"` and prompt text are missing.

- [ ] **Step 3: Implement workspace mode routing**

In `backend/agent/tools/computer_use.py`, add import:

```python
from agent.computer_use_workspace import WorkspaceActionError, workspace_worker
```

Add a helper:

```python
def _workspace_params(
    *,
    action: str,
    url: str,
    target: str,
    element: str,
    text: str,
    command: str,
    filename: str,
    amount: int,
    submit: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {"action": action}
    _put(params, "url", url)
    _put(params, "target", target)
    _put(params, "element", element)
    _put(params, "text", text)
    _put(params, "command", command)
    _put(params, "filename", filename)
    if amount:
        params["amount"] = amount
    if submit:
        params["submit"] = True
    return params
```

In `computer_use(...)`, add `submit: bool = False` if not already available, and before the final invalid-mode return add:

```python
    if selected_mode == "workspace":
        params = _workspace_params(
            action=action,
            url=url,
            target=target or ref,
            element=element,
            text=text,
            command=command or text,
            filename=filename,
            amount=amount,
            submit=submit,
        )
        computer_use_runtime.record_event(
            "tool_start",
            f"computer_use workspace {action} started.",
            tool="computer_use",
            data={"mode": "workspace", "action": action, "params": _public_params(params)},
        )
        try:
            result = workspace_worker.run(params)
        except WorkspaceActionError as exc:
            message = str(exc)
            computer_use_runtime.record_event(
                "tool_error",
                message,
                tool="computer_use",
                data={"mode": "workspace", "action": action},
            )
            return message
        computer_use_runtime.record_event(
            "tool_result",
            f"computer_use workspace {action} finished.",
            tool="computer_use",
            data={"mode": "workspace", "action": action, "result": result.data},
        )
        return result.message
```

- [ ] **Step 4: Update agent prompt**

In `backend/agent/graph/agent.py`, revise the computer-use tool description and rules:

```text
8. computer_use - Full local computer use. mode='workspace' controls Vellum's visible workspace for browser, click, type, scroll, terminal commands, and screenshots. Prefer mode='workspace' for computer-use tasks. mode='browser' controls the persistent Playwright browser directly. mode='desktop' controls the host OS and requires explicit runtime permission.
```

Add rule:

```text
- In computer-use mode, prefer computer_use(mode='workspace', ...) so the user can see Vellum operate in the visible workspace. Use mode='desktop' only for explicit host-laptop app control.
```

- [ ] **Step 5: Run tests to verify pass**

Run:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_computer_use.py::test_computer_use_routes_workspace_actions backend/tests/test_agent_prompt.py::test_agent_prompt_documents_workspace_mode -q
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```powershell
git add backend/agent/tools/computer_use.py backend/agent/graph/agent.py backend/tests/test_computer_use.py backend/tests/test_agent_prompt.py
git commit -m "feat: route computer-use tool through visible workspace"
```

---

## Task 4: Web UI Workspace Event Surface

**Files:**
- Modify: `frontend/ui/vellum-chat.html`
- Modify: `frontend/ui/vellum-chat-voice.test.js`

- [ ] **Step 1: Write failing UI wiring test**

Append to `frontend/ui/vellum-chat-voice.test.js`:

```javascript
test("computer-use feed recognizes workspace actions", () => {
  expect(html).toContain("workspace_action");
  expect(html).toContain("Workspace");
  expect(html).toContain("computer-use-workspace");
});
```

- [ ] **Step 2: Run test to verify fail**

Run:

```powershell
cd frontend
npm.cmd test -- ui/vellum-chat-voice.test.js
```

Expected: fail because workspace-specific UI strings are not present.

- [ ] **Step 3: Add workspace styling and labels**

In `frontend/ui/vellum-chat.html`, add CSS near existing computer-use feed styles:

```css
.computer-use-workspace {
  border-top: 1px solid rgba(244,237,226,0.08);
  padding: 9px 13px 12px;
  font-family: 'DM Sans', sans-serif;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--whisper);
}
.computer-use-workspace strong {
  color: var(--soft-ember);
  font-weight: 500;
}
```

Inside `<div class="computer-use-feed" id="computerUseFeed">`, after `computerUseEvents`, add:

```html
<div class="computer-use-workspace" id="computerUseWorkspace">
  Workspace <strong>waiting</strong>
</div>
```

Add DOM ref near existing computer-use refs:

```javascript
const computerUseWorkspace = $('computerUseWorkspace');
```

Update `handleComputerUsePayload(payload)`:

```javascript
if (payload.event && payload.event.kind === 'workspace_action') {
  computerUseWorkspace.innerHTML = `Workspace <strong>${escapeHtml(payload.event.data?.action || 'active')}</strong>`;
}
```

Use the existing `escapeHtml` function if it is already defined before this code. If it is defined later, replace the inline update with `textContent`:

```javascript
computerUseWorkspace.textContent = `Workspace ${payload.event.data?.action || 'active'}`;
```

- [ ] **Step 4: Run UI test to verify pass**

Run:

```powershell
cd frontend
npm.cmd test -- ui/vellum-chat-voice.test.js
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add frontend/ui/vellum-chat.html frontend/ui/vellum-chat-voice.test.js
git commit -m "feat: show workspace actions in computer-use feed"
```

---

## Task 5: Tauri Desktop Shell Scaffold

**Files:**
- Create: `desktop/package.json`
- Create: `desktop/vite.config.mjs`
- Create: `desktop/index.html`
- Create: `desktop/overlay.html`
- Create: `desktop/src/main.js`
- Create: `desktop/src/styles.css`
- Create: `desktop/src-tauri/Cargo.toml`
- Create: `desktop/src-tauri/tauri.conf.json`
- Create: `desktop/src-tauri/capabilities/default.json`
- Create: `desktop/src-tauri/src/main.rs`
- Create: `desktop/src-tauri/src/lib.rs`

- [ ] **Step 1: Check local prerequisites**

Run:

```powershell
node -v
npm -v
cargo --version
rustc --version
```

Expected: Node/npm installed. Cargo/rustc installed with MSVC-compatible Rust toolchain. If `cargo` is missing, stop and install Rust via `winget install --id Rustlang.Rustup`, then restart the terminal.

- [ ] **Step 2: Create desktop package**

Create `desktop/package.json`:

```json
{
  "name": "vellum-desktop",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "tauri dev",
    "dev:web": "vite --host 127.0.0.1 --port 1420",
    "build": "tauri build",
    "build:web": "vite build",
    "test": "node -e \"console.log('desktop smoke tests are manual for milestone 1')\""
  },
  "dependencies": {
    "@tauri-apps/api": "^2.0.0"
  },
  "devDependencies": {
    "@tauri-apps/cli": "^2.0.0",
    "vite": "^7.1.12"
  }
}
```

Create `desktop/vite.config.mjs`:

```javascript
import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
  },
  clearScreen: false,
});
```

Create `desktop/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Vellum Desktop</title>
    <link rel="stylesheet" href="/src/styles.css" />
  </head>
  <body>
    <main class="desktop-shell">
      <div class="mark"><em>v</em>ellum</div>
      <div class="status" id="status">connecting</div>
      <button id="openVellum">Open Vellum</button>
      <button id="enableComputer">Computer Use</button>
      <button id="disableComputer">Stand Down</button>
    </main>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
```

Create `desktop/overlay.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Vellum Computer Use</title>
    <style>
      html,
      body {
        margin: 0;
        width: 100%;
        height: 100%;
        background: transparent;
        pointer-events: none;
        overflow: hidden;
      }
      .aura {
        position: fixed;
        inset: 8px;
        border: 1px solid rgba(217, 119, 70, 0.7);
        box-shadow:
          inset 0 0 42px rgba(217, 119, 70, 0.22),
          0 0 52px rgba(217, 119, 70, 0.26);
      }
    </style>
  </head>
  <body>
    <div class="aura"></div>
  </body>
</html>
```

Create `desktop/src/styles.css`:

```css
:root {
  --graphite: #0c0c0e;
  --parchment: #ece6db;
  --whisper: rgba(236, 230, 219, 0.46);
  --ember: #d97746;
  --line: rgba(244, 237, 226, 0.12);
}
html, body {
  margin: 0;
  min-height: 100vh;
  background: var(--graphite);
  color: var(--parchment);
  font-family: "Segoe UI", sans-serif;
}
.desktop-shell {
  display: grid;
  gap: 14px;
  place-content: center;
  min-height: 100vh;
}
.mark {
  font-family: Georgia, serif;
  font-size: 42px;
  letter-spacing: -0.04em;
}
.status {
  color: var(--whisper);
  font-size: 11px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}
button {
  border: 1px solid var(--line);
  background: transparent;
  color: var(--parchment);
  padding: 10px 16px;
  cursor: pointer;
}
button:hover {
  border-color: var(--ember);
}
```

Create `desktop/src/main.js`:

```javascript
import { invoke } from "@tauri-apps/api/core";

const status = document.querySelector("#status");

async function refreshHealth() {
  try {
    const body = await invoke("backend_health");
    status.textContent = body.ok ? "backend ready" : "backend unreachable";
  } catch (err) {
    status.textContent = `backend unreachable`;
  }
}

document.querySelector("#openVellum").addEventListener("click", () => {
  invoke("open_vellum_window");
});

document.querySelector("#enableComputer").addEventListener("click", async () => {
  await invoke("set_overlay", { enabled: true });
  await fetch("http://127.0.0.1:8000/api/computer-use/enable", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: "tauri" }),
  });
});

document.querySelector("#disableComputer").addEventListener("click", async () => {
  await invoke("set_overlay", { enabled: false });
  await fetch("http://127.0.0.1:8000/api/computer-use/disable", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: "tauri" }),
  });
});

refreshHealth();
setInterval(refreshHealth, 5000);
```

- [ ] **Step 3: Create Tauri config and Rust code**

Create `desktop/src-tauri/Cargo.toml`:

```toml
[package]
name = "vellum-desktop"
version = "0.1.0"
description = "Vellum desktop shell"
authors = ["Vellum"]
edition = "2021"

[lib]
name = "vellum_desktop_lib"
crate-type = ["staticlib", "cdylib", "rlib"]

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tauri = { version = "2", features = [] }
ureq = { version = "2", features = ["json"] }
```

Create `desktop/src-tauri/tauri.conf.json`:

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "Vellum",
  "version": "0.1.0",
  "identifier": "local.vellum.desktop",
  "build": {
    "beforeDevCommand": "npm run dev:web",
    "beforeBuildCommand": "npm run build:web",
    "devUrl": "http://127.0.0.1:1420",
    "frontendDist": "../dist"
  },
  "app": {
    "windows": [
      {
        "label": "main",
        "title": "Vellum",
        "width": 420,
        "height": 520,
        "resizable": true,
        "center": true
      }
    ],
    "security": {
      "csp": null
    }
  },
  "bundle": {
    "active": false,
    "targets": "all"
  }
}
```

Create `desktop/src-tauri/capabilities/default.json`:

```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "Default Vellum desktop capability set",
  "windows": ["main", "overlay", "vellum"],
  "permissions": ["core:default"]
}
```

Create `desktop/src-tauri/src/main.rs`:

```rust
fn main() {
    vellum_desktop_lib::run()
}
```

Create `desktop/src-tauri/src/lib.rs`:

```rust
use serde::Serialize;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

#[derive(Serialize)]
struct Health {
    ok: bool,
}

#[tauri::command]
fn backend_health() -> Health {
    let ok = ureq::get("http://127.0.0.1:8000/api/health")
        .timeout(std::time::Duration::from_secs(2))
        .call()
        .map(|response| response.status() == 200)
        .unwrap_or(false);
    Health { ok }
}

#[tauri::command]
fn open_vellum_window(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("vellum") {
        window.show().map_err(|err| err.to_string())?;
        window.set_focus().map_err(|err| err.to_string())?;
        return Ok(());
    }
    WebviewWindowBuilder::new(
        &app,
        "vellum",
        WebviewUrl::External("http://127.0.0.1:5173/ui/vellum-chat.html?desktop=1".parse().unwrap()),
    )
    .title("Vellum")
    .inner_size(1280.0, 820.0)
    .center()
    .build()
    .map_err(|err| err.to_string())?;
    Ok(())
}

#[tauri::command]
fn set_overlay(app: tauri::AppHandle, enabled: bool) -> Result<(), String> {
    if enabled {
        show_overlay(app)
    } else {
        if let Some(window) = app.get_webview_window("overlay") {
            window.hide().map_err(|err| err.to_string())?;
        }
        Ok(())
    }
}

fn show_overlay(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("overlay") {
        window.show().map_err(|err| err.to_string())?;
        return Ok(());
    }
    let window = WebviewWindowBuilder::new(&app, "overlay", WebviewUrl::App("overlay.html".into()))
        .title("Vellum Computer Use")
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .fullscreen(true)
        .build()
        .map_err(|err| err.to_string())?;
    window.set_ignore_cursor_events(true).map_err(|err| err.to_string())?;
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![backend_health, open_vellum_window, set_overlay])
        .run(tauri::generate_context!())
        .expect("error while running Vellum desktop");
}
```

- [ ] **Step 4: Install desktop dependencies**

Run:

```powershell
cd desktop
npm.cmd install
```

Expected: dependencies installed and `package-lock.json` created under `desktop/`.

- [ ] **Step 5: Run Tauri metadata check**

Run:

```powershell
cd desktop
npm.cmd run dev
```

Expected: Tauri opens the Vellum desktop shell after starting the desktop Vite shell on port 1420. If Rust compilation fails because a method name differs in current Tauri, adjust only the Rust API call named in the compiler error and re-run.

- [ ] **Step 6: Commit**

```powershell
git add desktop scripts
git commit -m "feat: scaffold tauri desktop shell"
```

---

## Task 6: Desktop Startup Script

**Files:**
- Create: `scripts/start-desktop.ps1`

- [ ] **Step 1: Add startup script**

Create `scripts/start-desktop.ps1`:

```powershell
param()

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

& (Join-Path $PSScriptRoot "start.ps1")

Push-Location (Join-Path $Root "desktop")
try {
  if (-not (Test-Path "node_modules")) {
    npm.cmd install
  }
  npm.cmd run dev
} finally {
  Pop-Location
}
```

- [ ] **Step 2: Run script**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-desktop.ps1
```

Expected: backend and UI start, then Tauri desktop shell launches.

- [ ] **Step 3: Commit**

```powershell
git add scripts/start-desktop.ps1
git commit -m "chore: add desktop startup script"
```

---

## Task 7: End-To-End Workspace Smoke Path

**Files:**
- Modify: `backend/tests/test_api.py`
- No production code if prior tasks are correct.

- [ ] **Step 1: Add API smoke test for representative actions**

Append to `backend/tests/test_api.py`:

```python
def test_workspace_api_accepts_core_milestone_actions(monkeypatch):
    seen = []

    class FakeResult:
        def __init__(self, action):
            self.action = action
            self.status = "ok"
            self.message = f"{action} ok"
            self.data = {"action": action}

    class FakeWorker:
        def run(self, params):
            seen.append(params["action"])
            return FakeResult(params["action"])

    monkeypatch.setattr(api, "workspace_worker", FakeWorker())
    actions = [
        {"action": "browser.open", "url": "https://example.com"},
        {"action": "browser.navigate", "url": "https://example.com/docs"},
        {"action": "input.click", "target": "button[name=Search]"},
        {"action": "input.type", "target": "input[name=q]", "text": "vellum"},
        {"action": "input.scroll", "amount": 1},
        {"action": "terminal.run", "command": "echo hello"},
        {"action": "screen.screenshot", "filename": "workspace.png"},
    ]

    with TestClient(api.app) as client:
        responses = [client.post("/api/computer-use/workspace/action", json=action) for action in actions]

    assert [response.status_code for response in responses] == [200] * len(actions)
    assert seen == [action["action"] for action in actions]
```

- [ ] **Step 2: Run smoke test**

Run:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_api.py -k workspace_api_accepts_core_milestone_actions -q
```

Expected: 1 passed.

- [ ] **Step 3: Run focused regression suite**

Run:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_computer_use_workspace.py backend/tests/test_computer_use.py backend/tests/test_api.py backend/tests/test_agent_prompt.py -q
cd frontend
npm.cmd test -- ui/vellum-chat-voice.test.js
```

Expected: all selected backend tests pass and the UI voice test passes.

- [ ] **Step 4: Manual smoke checklist**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-desktop.ps1
```

Manual expected behavior:

- Vellum desktop shell opens.
- `Open Vellum` opens the existing Vellum UI inside a Tauri window.
- `Computer Use` enables mode and shows the whole-screen orange overlay.
- `Stand Down` hides the overlay and disables mode.
- POSTing to `/api/computer-use/workspace/action` with `browser.open` opens a visible Playwright browser tab/window if Playwright MCP is configured.
- POSTing with `terminal.run` returns command output in the API response and records a computer-use event.

- [ ] **Step 5: Commit**

```powershell
git add backend/tests/test_api.py
git commit -m "test: cover milestone workspace smoke actions"
```

---

## Task 8: Verification And Documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-05-25-vellum-desktop-sandbox-milestones-design.md` only if implementation discovers a necessary scope correction.

- [ ] **Step 1: Full focused verification**

Run:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_computer_use_workspace.py backend/tests/test_computer_use.py backend/tests/test_api.py backend/tests/test_agent_prompt.py backend/tests/test_voice_api.py -q
cd frontend
npm.cmd test -- ui/vellum-chat-voice.test.js ui/terminal/terminal-workspace.test.js ui/terminal/commands.test.js
cd ..\desktop
npm.cmd run test
```

Expected:

- Backend selected tests pass.
- Frontend selected tests pass.
- Desktop JS tests pass if any were added; if none exist, `node --test` exits successfully with zero tests or no matching test files depending on Node version. If it fails due to no test files, change `desktop/package.json` test script to:

```json
"test": "node -e \"console.log('desktop smoke tests are manual for milestone 1')\""
```

- [ ] **Step 2: Manual verification**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-desktop.ps1
```

Verify:

- Desktop shell launches.
- Backend status reads ready.
- Main Vellum window opens.
- Overlay appears and disappears.
- Existing browser/terminal APIs still work.

- [ ] **Step 3: Final commit for any verification-only fixes**

If verification required a small fix:

```powershell
git add <changed-files>
git commit -m "fix: stabilize desktop workspace milestone"
```

If no files changed, skip this commit.

---

## Risk Notes

- This milestone is a controlled workspace, not true Windows Sandbox or Hyper-V isolation.
- Tauri overlay APIs may need one compiler-driven adjustment depending on the installed Tauri v2 crate version.
- Playwright visible browser behavior depends on the existing Playwright MCP configuration.
- Terminal command execution is intentionally narrow and evented; it is not yet a durable task memory system.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-25-vellum-desktop-sandbox-milestone-1.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.
