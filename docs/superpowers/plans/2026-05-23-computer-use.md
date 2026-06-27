# Full Computer Use Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Vellum computer use with full OS desktop control and Playwright browser automation.

**Architecture:** Add a local desktop backend using lazily imported `pyautogui`, expose it through a unified `computer_use` tool, and extend the Playwright MCP wrapper with browser computer-use actions. Desktop input is gated by configuration; browser mutations reuse the existing Playwright mutation gate.

**Tech Stack:** Python, LangChain tools, Pydantic settings, Playwright MCP, pyautogui, pytest.

---

## Files

- Create: `backend/agent/tools/desktop.py` for local OS desktop control.
- Create: `backend/agent/tools/computer_use.py` for unified desktop/browser routing.
- Modify: `backend/agent/mcp/playwright_tools.py` to add browser computer-use actions and target/ref normalization.
- Modify: `backend/agent/tools/browser.py` only if existing tool wrappers need parameter compatibility.
- Modify: `backend/agent/graph/agent.py` to register and prompt the new tool.
- Modify: `backend/agent/config.py`, `backend/requirements.txt`, and `backend/pyproject.toml` for settings and dependencies.
- Create: `backend/tests/test_computer_use.py` for desktop and unified routing tests.
- Modify: `backend/tests/test_mcp_tools.py` for expanded browser MCP mappings.

## Plan Audit

- **Spec coverage:** Desktop observe/input, browser automation, settings gates, dependency handling, and tests are all represented below.
- **Placeholder scan:** No placeholder steps remain.
- **Type consistency:** `target` is the browser MCP canonical field; `ref` remains an accepted alias. Desktop coordinates use integer `x` and `y`. Form fields are passed as `fields_json`.
- **Failure modes:** Tests include disabled desktop gate and invalid form JSON. Runtime code must return text errors instead of raising into the agent.
- **YAGNI:** OCR, app launching, process management, and vendor-native CUA loops are excluded.

---

### Task 1: Desktop Backend Tests

**Files:**
- Create: `backend/tests/test_computer_use.py`
- Create later: `backend/agent/tools/desktop.py`

- [ ] **Step 1: Write failing tests for desktop actions**

Add tests that import `agent.tools.desktop`, monkeypatch `_pyautogui`, and verify:

```python
def test_desktop_screenshot_saves_file(monkeypatch, tmp_path):
    fake = FakePyAutoGui()
    monkeypatch.setattr(desktop_tools, "_pyautogui", lambda: fake)
    monkeypatch.setattr(desktop_tools, "_screenshot_dir", lambda: tmp_path)

    result = desktop_tools.run_desktop_action({"action": "screenshot", "filename": "screen.png"})

    assert "screen.png" in result
    assert fake.screenshot_saved_to.name == "screen.png"


def test_desktop_click_requires_gate(monkeypatch):
    monkeypatch.setattr(desktop_tools, "_desktop_allowed", lambda: False)

    result = desktop_tools.run_desktop_action({"action": "click", "x": 10, "y": 20})

    assert "requires COMPUTER_USE_ALLOW_DESKTOP=true" in result


def test_desktop_click_when_enabled(monkeypatch):
    fake = FakePyAutoGui()
    monkeypatch.setattr(desktop_tools, "_pyautogui", lambda: fake)
    monkeypatch.setattr(desktop_tools, "_desktop_allowed", lambda: True)

    result = desktop_tools.run_desktop_action({"action": "click", "x": 10, "y": 20, "button": "left"})

    assert result == "Desktop click completed at 10,20."
    assert fake.calls == [("click", 10, 20, "left", 1)]
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_computer_use.py -k desktop -v`

Expected: import failure because `agent.tools.desktop` does not exist.

### Task 2: Desktop Backend Implementation

**Files:**
- Create: `backend/agent/tools/desktop.py`
- Modify: `backend/agent/config.py`

- [ ] **Step 1: Add settings**

Add fields:

```python
computer_use_allow_desktop: bool = Field(default=False, alias="COMPUTER_USE_ALLOW_DESKTOP")
computer_use_screenshot_dir: Path = Field(default=Path("data/computer-use/screenshots"), alias="COMPUTER_USE_SCREENSHOT_DIR")
```

Resolve `computer_use_screenshot_dir` with `_resolve_against_repo`.

- [ ] **Step 2: Implement desktop action runner**

Implement `run_desktop_action(params: dict[str, Any]) -> str` with lazy `pyautogui` import, `FAILSAFE=True`, screenshot saving, position, size, and gated input actions.

- [ ] **Step 3: Run desktop tests**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_computer_use.py -k desktop -v`

Expected: desktop tests pass.

### Task 3: Browser Computer-Use Mappings

**Files:**
- Modify: `backend/tests/test_mcp_tools.py`
- Modify: `backend/agent/mcp/playwright_tools.py`

- [ ] **Step 1: Write failing browser mapping tests**

Add tests for:

```python
def test_playwright_click_uses_target_alias(monkeypatch):
    fake_session = FakeSession(tools=["browser_click"], text="clicked")
    monkeypatch.setattr(playwright_tools, "_mutations_allowed", lambda: True)
    monkeypatch.setattr(playwright_tools, "stdio_client", lambda params: AsyncPairContext())
    monkeypatch.setattr(playwright_tools, "ClientSession", lambda read, write: fake_session)

    result = asyncio.run(playwright_tools.run_tool_async({"action": "click", "target": "button[name=Go]"}))

    assert result == "clicked"
    assert fake_session.calls[0] == ("browser_click", {"target": "button[name=Go]"})
```

Also add screenshot/resize/drag/fill_form tests.

- [ ] **Step 2: Run tests and verify they fail**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_mcp_tools.py -k "target_alias or screenshot or resize or drag or fill_form" -v`

Expected: unsupported action or wrong parameter names.

- [ ] **Step 3: Implement mappings**

Add READ actions for screenshot, resize, console, network. Add gated actions for evaluate, drag, fill_form. Normalize element targeting to `target`.

- [ ] **Step 4: Run browser mapping tests**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_mcp_tools.py -k "playwright" -v`

Expected: Playwright tests pass.

### Task 4: Unified Computer Use Tool

**Files:**
- Create: `backend/agent/tools/computer_use.py`
- Modify: `backend/agent/graph/agent.py`
- Test: `backend/tests/test_computer_use.py`

- [ ] **Step 1: Write failing unified tool tests**

Add tests that monkeypatch `desktop_tools.run_desktop_action` and `playwright_run`, then call `computer_use.invoke(...)` for both modes.

- [ ] **Step 2: Run tests and verify they fail**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_computer_use.py -k computer_use -v`

Expected: `agent.tools.computer_use` does not exist.

- [ ] **Step 3: Implement `computer_use` tool**

Create a LangChain `@tool` that accepts primitive string/number/boolean parameters and routes by `mode`.

- [ ] **Step 4: Register the tool**

Import `computer_use` in `agent/graph/agent.py`, add it to sync/async tool lists, and add prompt rules for desktop safety and browser preference.

- [ ] **Step 5: Run unified tests**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_computer_use.py tests/test_agent_prompt.py -v`

Expected: tests pass.

### Task 5: Dependencies And Verification

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add dependencies**

Add:

```text
pyautogui>=0.9.54
pillow>=10.0.0
```

- [ ] **Step 2: Install dependencies into local venv**

Run: `..\.venv\Scripts\python.exe -m pip install pyautogui>=0.9.54 pillow>=10.0.0`

Expected: packages install successfully.

- [ ] **Step 3: Run full relevant test suite**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_computer_use.py tests/test_mcp_tools.py tests/test_agent_prompt.py tests/test_config.py tests/test_api.py tests/test_voice_api.py`

Expected: all selected tests pass.

- [ ] **Step 4: Restart backend**

Restart the local FastAPI backend on `127.0.0.1:8000` and verify `/api/health` returns 200.

