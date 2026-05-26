# Vellum Computer Use Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the failed demo-style computer-use prototype with a production-grade session architecture where clicking Computer Use visibly gives Vellum control of the laptop and routes user instructions into real desktop, browser, terminal, and screenshot actions.

**Architecture:** Keep FastAPI as the agent brain and Tauri as the desktop shell, but add a first-class `ComputerUseSession` service between UI/voice/chat and low-level tools. The session owns lifecycle, permissions, overlay state, observation, action execution, event streaming, stop/pause, and learning hooks. Browser work continues to use the persistent Playwright MCP path; host laptop control uses a Windows desktop driver behind a swappable interface.

**Tech Stack:** FastAPI, LangChain tools, existing Vellum memory/learning hooks, Playwright MCP, pyautogui/mss/Windows ShellExecute for host control, Tauri/Rust for the visible desktop shell and full-screen activity overlay.

---

## Current Setup Summary

- `desktop/index.html` and `desktop/src/main.js` expose `Open Vellum`, `Computer Use`, `Test Control`, and `Stand Down`.
- `Computer Use` currently calls `/api/computer-use/enable`, which toggles runtime state and tries to start an overlay.
- `Test Control` calls `/api/computer-use/desktop/demo`, which runs a hard-coded Notepad demo. This does not match the desired product experience and should be removed.
- `backend/agent/tools/desktop.py` already has useful host actions: screenshot, move, click, scroll, type, terminal, app launch, and permission grants.
- `backend/agent/mcp/playwright_tools.py` and `backend/agent/tools/browser.py` already cover persistent browser actions.
- `backend/agent/computer_use_workspace.py` is a narrow workspace worker, but it does not create a true visible sandbox or a session loop.
- The missing piece is orchestration: user instruction -> observe screen -> choose action -> execute action -> return result/screenshot -> continue until done or blocked.

## Design Decision

Do not move to voice/Jarvis Milestone 2 yet. First make Milestone 1 real and testable:

- The user clicks `Computer Use`.
- Vellum starts a durable computer-use session.
- A full-screen orange glow/overlay becomes visible across the laptop display.
- Vellum can execute visible actions: open apps, open browser, click, type, scroll, run terminal commands, take screenshots.
- User instructions from text and voice route into the session while it is active.
- Every action emits events and is saved for learning/memory/Obsidian integration.
- `Stand Down`, API stop, and an emergency escape path stop the session reliably.

This is host-laptop control, not a strong VM sandbox. A real isolated sandbox can be added later as a second driver.

## Brainstorm Audit

1. **Assumption-check:** Do not assume the current overlay works; it has already failed. The plan treats overlay as a separate driver with health checks.
2. **Architecture stress:** Long-running tasks need session state, cancellation, retries, and event logs. One-off endpoints are insufficient.
3. **Alternative dismissal:** Docker was considered and rejected by user. A host Windows driver is the right near-term path for visible control.
4. **Requirement gap:** Current code does not route normal instructions into computer-use actions. The plan adds active-mode routing.
5. **Composability claim:** Browser and desktop actions compose only through a session router, not by exposing unrelated tools.
6. **Scope honesty:** Voice wake-word/Jarvis mode is deferred. This plan covers reliable visible control first.
7. **API surface drift:** Keep legacy endpoints temporarily as wrappers, but create versioned session endpoints for the real API.
8. **Failure mode map:** Overlay failure, pyautogui missing, browser transport breakage, permission denial, and infinite loops each get explicit handling.
9. **YAGNI sweep:** Remove `Test Control` and the hard-coded demo. Manual smoke tests can use explicit session actions instead.

Accepted risk: host-laptop control is powerful and not isolated. Mitigation is explicit mode, visible overlay, permissions, event logs, and emergency stop.

## File Structure

- `backend/agent/computer_use/session.py` - session lifecycle, active task loop, stop/pause, event emission, learning hooks.
- `backend/agent/computer_use/driver.py` - protocol for screenshot/mouse/keyboard/app/terminal actions.
- `backend/agent/computer_use/windows_driver.py` - Windows host implementation using pyautogui, mss/PIL screenshots, ShellExecute, and terminal helpers.
- `backend/agent/computer_use/overlay.py` - backend API for starting/stopping/verifying the activity overlay.
- `backend/agent/computer_use/router.py` - routes model-requested actions to browser, desktop, or terminal drivers.
- `backend/agent/api.py` - replace demo endpoints with session endpoints and route active-mode chat/voice instructions.
- `backend/agent/tools/computer_use.py` - keep as the LangChain tool surface, but delegate to the session router when active.
- `backend/agent/graph/agent.py` - prompt rules for observe-then-act, screenshots after actions, permission escalation, and stop behavior.
- `backend/tests/test_computer_use_session.py` - fake-driver lifecycle and loop tests.
- `backend/tests/test_computer_use_api.py` - session API tests.
- `backend/tests/test_computer_use_router.py` - browser/desktop routing tests.
- `desktop/index.html` - remove `Test Control`; keep `Computer Use` and `Stand Down`.
- `desktop/src/main.js` - call session endpoints, subscribe to status/events, avoid buttons hanging forever.
- `desktop/src-tauri/src/lib.rs` - own a reliable full-screen overlay/window command or sidecar lifecycle.
- `docs/superpowers/specs/2026-05-25-vellum-desktop-sandbox-milestones-design.md` - update language from "sandbox" to "host-visible control first, sandbox later."

---

## Task 1: Add Session Tests First

**Files:** `backend/tests/test_computer_use_session.py`

- [ ] Create fake `ComputerDriver`, fake overlay, fake browser router, and fake learner classes.
- [ ] Test `start()` sets active status and starts overlay exactly once.
- [ ] Test `stop()` cancels active work, stops overlay, records an event, and returns to default mode.
- [ ] Test `submit_task("open notepad")` calls the action loop with the current session id.
- [ ] Test a task emits ordered events: task_started, screenshot, action_started, action_finished, task_finished.
- [ ] Test action loop stops after max iterations and reports `needs_user` instead of hanging.
- [ ] Test overlay start failure returns a clear error and does not leave mode half-enabled.
- [ ] Run:
  ```powershell
  .venv\Scripts\python.exe -m pytest backend/tests/test_computer_use_session.py -q
  ```
- [ ] Confirm tests fail because the session module does not exist yet.

## Task 2: Implement ComputerUseSession

**Files:** `backend/agent/computer_use/session.py`, `backend/agent/computer_use/__init__.py`

- [ ] Define `ComputerUseSessionState` with `session_id`, `enabled`, `status`, `task`, `started_at`, `last_error`, and `permissions`.
- [ ] Define `ComputerUseEvent` with stable event types and serializable `data`.
- [ ] Implement `start(source, task=None)` with idempotent behavior.
- [ ] Implement `stop(reason=None)` with cancellation and overlay cleanup.
- [ ] Implement `pause()` and `resume()`.
- [ ] Implement `submit_task(text, source, thread_id)` that records the user instruction and schedules the action loop.
- [ ] Add `max_steps`, `step_timeout_seconds`, and `stop_requested` guards.
- [ ] Connect to `computer_use_runtime.record_event` so the existing event feed continues to work.
- [ ] Run the session tests and make them pass.

## Task 3: Create a Driver Interface and Windows Driver

**Files:** `backend/agent/computer_use/driver.py`, `backend/agent/computer_use/windows_driver.py`, `backend/tests/test_computer_use_driver.py`

- [ ] Write tests for screenshot path creation, mouse action payload validation, app launch command mapping, and terminal command launch.
- [ ] Define `ComputerDriver` protocol: `health_check`, `screen_size`, `screenshot`, `move`, `click`, `double_click`, `right_click`, `drag`, `scroll`, `type_text`, `press_key`, `hotkey`, `open_app`, `open_terminal`, `run_terminal_command`.
- [ ] Move reusable validation from `backend/agent/tools/desktop.py` into the driver layer without changing public behavior.
- [ ] Prefer `mss` for screenshots if available; fall back to pyautogui screenshot.
- [ ] Keep `pyautogui.FAILSAFE = True`.
- [ ] Keep permission gates for `desktop_control`, `terminal`, and `open_apps`.
- [ ] Return structured results, not only strings.
- [ ] Run:
  ```powershell
  .venv\Scripts\python.exe -m pytest backend/tests/test_computer_use_driver.py -q
  ```

## Task 4: Replace Demo Endpoint With Session API

**Files:** `backend/agent/api.py`, `backend/tests/test_computer_use_api.py`

- [ ] Add `POST /api/computer-use/session/start`.
- [ ] Add `POST /api/computer-use/session/stop`.
- [ ] Add `POST /api/computer-use/session/pause`.
- [ ] Add `POST /api/computer-use/session/resume`.
- [ ] Add `POST /api/computer-use/session/task`.
- [ ] Add `GET /api/computer-use/session/status`.
- [ ] Keep `/api/computer-use/enable` and `/api/computer-use/disable` as compatibility wrappers to start/stop session.
- [ ] Delete `/api/computer-use/desktop/demo`, `_run_desktop_control_demo`, `_desktop_demo_call`, and `ComputerUseDemoRequest`.
- [ ] Route text intents like "enable computer use", "turn on computer use", "disable computer use", "stand down", and "stop computer use" to session start/stop.
- [ ] When computer use is active and the user sends a normal instruction, route it to `/session/task` behavior instead of normal chat-only response.
- [ ] Run:
  ```powershell
  .venv\Scripts\python.exe -m pytest backend/tests/test_computer_use_api.py -q
  ```

## Task 5: Build the Observe-Act Loop

**Files:** `backend/agent/computer_use/router.py`, `backend/agent/tools/computer_use.py`, `backend/agent/graph/agent.py`, `backend/tests/test_computer_use_router.py`

- [ ] Define a normalized action schema: `screenshot`, `click`, `double_click`, `move`, `drag`, `scroll`, `type`, `keypress`, `open_app`, `open_terminal`, `run_terminal`, `browser_open`, `browser_tabs`, `browser_click`, `browser_type`, `browser_scroll`, `wait`, `done`, `needs_user`.
- [ ] Route browser-only actions to Playwright MCP.
- [ ] Route host OS actions to `WindowsComputerDriver`.
- [ ] After every mutating action, capture a screenshot and record it in the event stream.
- [ ] Add loop limits and timeouts.
- [ ] Add "needs_user" handling for login, passwords, UAC prompts, captchas, payment, deletion, or irreversible actions.
- [ ] Update agent prompt so it verifies the screen after each action instead of assuming success.
- [ ] Run router and prompt tests.

## Task 6: Make the Overlay Reliable

**Files:** `backend/agent/computer_use/overlay.py`, `desktop/src-tauri/src/lib.rs`, `desktop/overlay.html`, `desktop/src/styles.css`, `backend/tests/test_computer_use_session.py`

- [ ] Treat the overlay as part of session health, not decoration.
- [ ] Replace the backend Tk overlay as the primary path with a Tauri-owned full-screen always-on-top overlay.
- [ ] Ensure the overlay is click-through/focusless so Vellum can still click apps underneath.
- [ ] Add `show_computer_use_overlay`, `hide_computer_use_overlay`, and `overlay_status` Tauri commands.
- [ ] Add backend overlay adapter that can call Tauri when available and fail clearly when unavailable.
- [ ] Keep a fallback backend overlay only for development, but do not mark session fully ready if the overlay cannot be verified.
- [ ] Add a manual Windows smoke check: enable session, confirm full-screen orange glow is visible, click-through works, stand down closes it.

## Task 7: Fix Desktop Shell UX

**Files:** `desktop/index.html`, `desktop/src/main.js`, `desktop/src/styles.css`

- [ ] Remove `Test Control`.
- [ ] `Computer Use` calls `/api/computer-use/session/start`.
- [ ] `Stand Down` calls `/api/computer-use/session/stop`.
- [ ] Add a visible session state line: ready, active, working, paused, needs user, stopping, error.
- [ ] Add fetch timeout handling that always re-enables buttons.
- [ ] Subscribe to `/api/computer-use/events` and show the latest action status.
- [ ] Make the app close normally even if backend calls hang.
- [ ] Run Tauri dev and test button responsiveness.

## Task 8: Integrate Learning and Obsidian Logging

**Files:** `backend/agent/computer_use/session.py`, existing memory/Obsidian modules, tests as needed

- [ ] On session start, create a task log object with task text, source, thread id, and start time.
- [ ] For every action, append concise action metadata: app, command, URL, click coordinate, typed text redacted where needed, screenshot path.
- [ ] On task finish, call existing background learning with source `computer_use`.
- [ ] Add an Obsidian note under the existing Vellum vault pattern for computer-use task summaries.
- [ ] Redact likely secrets before memory/Obsidian writes.

## Task 9: Manual Production Smoke Test

**Files:** no code unless failures are found

- [ ] Start backend and desktop shell.
- [ ] Click `Computer Use`.
- [ ] Verify orange overlay covers the laptop screen, not only the Vellum tab.
- [ ] Type in Vellum: `open notepad and type hello from vellum`.
- [ ] Verify Notepad opens and text is visibly typed.
- [ ] Type: `open terminal and run echo vellum`.
- [ ] Verify terminal opens visibly and runs the command.
- [ ] Type: `open browser and search for OpenAI`.
- [ ] Verify browser opens through Playwright/browser path and visible actions happen.
- [ ] Type: `scroll down`.
- [ ] Verify visible scrolling.
- [ ] Click `Stand Down`.
- [ ] Verify overlay disappears and no stuck windows/processes remain.
- [ ] Run:
  ```powershell
  .venv\Scripts\python.exe -m pytest backend/tests/test_computer_use_session.py backend/tests/test_computer_use_driver.py backend/tests/test_computer_use_router.py backend/tests/test_computer_use_api.py backend/tests/test_mcp_tools.py -q
  ```

## Plan Audit

- **Does this fix the actual user complaint?** Yes. It removes the fake `Test Control` path and makes `Computer Use` itself start visible control.
- **Does it explain why the current build does nothing?** Yes. Current code toggles mode and demo endpoints but lacks a durable instruction-to-action session loop.
- **Does it overpromise sandboxing?** No. It explicitly calls the first pass host-laptop control and defers true isolation.
- **Does it preserve existing useful work?** Yes. It keeps Playwright MCP, desktop primitives, runtime events, and learning hooks.
- **Does it protect the user?** Partially. It adds explicit mode, visible overlay, permission gates, event logs, loop limits, and stop controls. Enterprise-grade isolation remains a later milestone.
- **Is the first implementation slice testable?** Yes. Session, driver, router, API, and UI can each be tested independently, with one manual Windows smoke test for visible control.

## Recommendation

Execute this plan before voice/Jarvis mode. Voice should sit on top of a working computer-use session; otherwise it will only make the broken path easier to trigger.
