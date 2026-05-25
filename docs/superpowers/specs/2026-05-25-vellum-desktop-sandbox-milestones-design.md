# Vellum Desktop Sandbox Milestones Design

## Purpose

Vellum should feel like an always-present desktop teammate with its own working computer. The long-term product should feel Jarvis-like: the user can speak naturally, Vellum can answer aloud, take over a visible workspace, use browser and terminal, recover from errors, and learn from conversations and actions.

This design sets the milestone scope before implementation. It prioritizes the first proof the user wants to see: Vellum visibly clicking, typing, scrolling, opening a browser, and running commands in a controlled sandbox/workspace.

## Product Direction

Vellum will keep one agent brain and add a native desktop body.

- The existing FastAPI backend remains the brain: model routing, memory, Obsidian, tools, MCP, permissions, and task state.
- A new Tauri desktop shell becomes the body: full-screen orange presence overlay, mode controls, visible workspace frame, emergency stop, and bridge to backend.
- A sandbox worker becomes Vellum's laptop: controlled browser, terminal, screen capture, input actions, and command execution.

Tauri is preferred over Electron because Vellum is expected to stay open for long periods. Tauri gives a lighter native shell, a Rust layer for OS integration, and a smaller attack surface. The backend remains independent so the shell can be replaced later if needed.

## Milestone 1: Visible Sandbox Operation

Goal: make Vellum visibly operate inside its own controlled workspace.

User-visible outcomes:

- User opens Vellum Desktop.
- User enables computer-use mode.
- A full-screen orange overlay appears outside the browser tab.
- A visible sandbox/workspace window appears.
- Vellum can perform basic actions in that workspace:
  - open browser
  - navigate to a URL
  - click
  - type
  - scroll
  - open terminal
  - run a command
  - take a screenshot
- User can stop/disable computer-use immediately.

Implementation boundaries:

- This milestone does not require always-listening voice.
- This milestone does not require long-term action memory.
- This milestone does not require a full Windows Sandbox or Hyper-V VM on day one. The first worker can be a controlled local workspace process as long as it is visibly separate from the user-facing Vellum UI and all mutating actions are gated.

Recommended technical shape:

- Add `desktop/` or `apps/desktop/` Tauri app.
- Tauri hosts the existing Web UI or a slim desktop-specific view.
- Tauri manages:
  - always-on-top transparent overlay window for orange glow
  - main Vellum window
  - computer-use mode state display
  - stop/disable controls
  - backend process health
- Backend exposes sandbox action endpoints/events.
- Sandbox worker exposes a small action protocol:
  - `browser.open`
  - `browser.navigate`
  - `input.click`
  - `input.type`
  - `input.scroll`
  - `terminal.open`
  - `terminal.run`
  - `screen.screenshot`
  - `session.stop`
- The existing agent should call the existing `computer_use` tool first where possible, with the worker implementation behind that tool evolving from current local Playwright/desktop actions into the sandbox worker.

## Milestone 2: Voice-First Jarvis Mode

Goal: remove the mic-button feel and make Vellum ambient.

User-visible outcomes:

- Vellum listens without the user clicking a mic button.
- Voice activation supports phrases such as:
  - "Vellum"
  - "turn on computer use"
  - "take over"
  - "disable computer use"
  - "stand down"
  - "pause"
  - "continue"
- Vellum speaks concise progress while working.
- User can interrupt with voice.

Implementation boundaries:

- Always-listening must have clear privacy controls.
- Wake/listen state must be visible.
- Raw audio should remain transient unless the user explicitly opts into saving clips.
- Browser-only microphone capture is not enough for the final product; Tauri should own the microphone permission and listening loop.

## Milestone 3: Computer-Use Sessions And Learning

Goal: make Vellum learn from what it does, not only from chat.

User-visible outcomes:

- Vellum remembers workflows and corrections.
- Vellum learns preferred apps and commands.
- Vellum can say what it tried, what failed, and what it will do differently next time.

Data captured:

- Conversation turns from text and voice.
- Structured action events:
  - action type
  - target app or browser tab
  - command, redacted when sensitive
  - result
  - error
  - screenshot path when relevant
- Task summaries.
- User corrections.

Memory sinks:

- Existing `_background_learn()` path for conversation summaries.
- FTS5/Honcho for searchable memory.
- Obsidian notes under `Agent/Memories/Computer Use/`.
- Existing project context tick path when a session belongs to an active project.

## Milestone 4: Strong Sandbox Isolation

Goal: replace the first controlled workspace with a stronger isolation boundary.

Options:

- Windows Sandbox.
- Hyper-V VM.
- Dedicated local user session.
- Containerized browser/terminal worker where OS-level desktop apps are not required.

Selection criteria:

- visible screen stream
- reliable input injection
- command execution
- resettable state
- explicit host folder bridges
- predictable startup latency
- production support on Windows

The first implementation should not pretend to be fully isolated if it is not. UI labels should say "workspace" until the underlying isolation is a true sandbox.

## Milestone 5: Enterprise Reliability Layer

Goal: make computer-use robust enough for long-running production use.

Requirements:

- action timeouts
- retries with limits
- structured errors
- kill switch
- action audit log
- permission model
- crash recovery
- stale browser/session cleanup
- health checks
- versioned action protocol
- deterministic tests for action routing
- smoke tests against a fake worker

## Mode Language

Enable phrases:

- enable computer use
- turn on computer use
- start computer use
- take over
- take control
- control my laptop
- control my computer
- use my laptop
- use my computer
- enter computer mode
- start desktop mode

Disable phrases:

- disable computer use
- turn off computer use
- stop computer use
- exit computer mode
- stand down
- release control
- give control back
- back to normal
- default mode
- stop controlling my laptop
- stop controlling my computer

Pause/resume phrases:

- pause
- hold on
- wait
- freeze
- stop for a second
- continue
- resume
- carry on
- keep going

## Architecture Boundaries

### Backend

The backend remains the source of truth for:

- agent graph
- model selection
- memory
- Obsidian
- MCP tools
- permissions
- computer-use state
- action events
- task/session state

### Tauri Shell

The Tauri shell owns:

- native desktop window
- whole-screen orange overlay
- tray/status controls
- microphone permission surface
- emergency stop
- local process supervision
- user-visible workspace frame

The shell must not become a second agent brain.

### Sandbox Worker

The worker owns:

- visible browser/terminal workspace
- screenshots
- mouse/keyboard actions inside the workspace
- command execution inside the workspace
- worker health and lifecycle

The worker must communicate through a narrow action protocol. The backend should not depend on implementation details of the worker UI.

## Safety And Privacy

- Computer-use mode is explicit.
- Disable/stop must be always available.
- Dangerous host actions require permission.
- Secrets, passwords, account settings, banking, purchases, and destructive actions remain blocked unless future requirements explicitly design a safe approval path.
- Raw audio is transient by default.
- Commands and typed text are redacted before storage when they may contain secrets.
- The UI must distinguish "workspace" from "sandbox" until true isolation is implemented.

## Testing Strategy

Milestone 1 tests should be deterministic and not depend on a real desktop:

- backend unit tests for mode phrase detection
- backend unit tests for action routing into the worker client
- backend unit tests for event streaming
- fake worker tests for click/type/scroll/browser/terminal actions
- Tauri-side smoke tests can be manual initially, but Rust command handlers should be unit-tested where practical
- frontend/Web UI tests should verify mode controls and event feed wiring

Real desktop/sandbox integration tests can be added later as opt-in smoke tests because they require local OS capabilities.

## Brainstorm Audit

1. Assumption-check: Tauri can provide the native shell and overlay, but sandbox implementation details remain open. Accepted as a milestone decision because Milestone 1 only promises a controlled workspace, not full VM isolation.
2. Architecture stress: Backend, shell, and worker are separated so failures can be isolated. Worker death should not kill the agent brain.
3. Alternative dismissal: Electron was considered and rejected for Vellum's always-on footprint. Backend independence keeps the decision reversible.
4. Requirement gap: The user wants visible action first. This spec makes visible sandbox operation Milestone 1 and moves learning to Milestone 3.
5. Composability claim: Components compose through a narrow action protocol and event stream, not shared UI state.
6. Scope honesty: Full Jarvis voice, memory, and VM sandboxing are separate milestones.
7. API surface drift: Action protocol uses semantic names rather than tool-specific implementation names.
8. Failure mode map: Worker crashes, backend crashes, permission denial, timeout, and unsupported action are handled by event/error reporting and stop controls.
9. YAGNI sweep: No Electron, no full memory session model, and no always-listening voice in Milestone 1.

## Immediate Next Step

Write an implementation plan for Milestone 1 only: Tauri shell plus a controlled sandbox/workspace action bridge that can visibly run browser, click, type, scroll, terminal, command, and screenshot actions.
