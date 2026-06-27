# Coding Assistant SDK MVP

Date: 2026-06-05
Status: design approved, awaiting implementation plan
Surface: `design/Velllum/uploads/vellum-workspace.html` as the visual source, migrated into the real Vellum desktop/frontend app

## Goal

Build the first real, usable Coding Assistant mode for Vellum. The MVP must let a user choose a local project folder, select Codex or Claude Code, run a coding turn through the provider's Python SDK, stream the real response/events into the existing Vellum workspace UI, and keep terminal/browser/files visible inside the same desktop app.

The MVP must remove preview-only behavior from the coding path. No fake subagents, fake progress, fake task fixtures, fake file trees, or fake diffs should appear in the working app. Empty real state is acceptable. Demo data is not.

## Product Boundary

Coding Assistant is a Vellum mode/profile, not a separate product shell.

Keep:

- The existing Vellum desktop continuity from `vellum-workspace.html`: dark workspace, Geist typography, top chrome, left sidebar, central chat, mode switch, composer, and workspace side tabs.
- Existing real backend surfaces where possible: `/api/terminal/ws`, `/api/computer-use/workspace/action`, `/api/models`, `/api/memory/entries`, and current computer-use/browser routing.
- The mode switch mental model: General, Coding, Computer.

Change:

- Coding mode becomes SDK-backed and project-aware.
- Coding messages route to a new backend Coding Session service instead of the current browser-only OpenRouter planner/subagent preview.
- Workspace tabs show real connected surfaces only. If a real source is unavailable, show a concise setup/empty state.

Defer:

- Multi-agent orchestration, review gates, automatic task splitting, memory-heavy coding behavior, autonomous commits, cloud/background workers, and fake Codex-style subagent timelines.
- Rich inline diff review, unless the SDK returns real patch/file-change events that can be mapped safely.

## Source Evidence

OpenAI's Codex SDK Python docs state that `openai-codex` controls the local Codex app-server over JSON-RPC, supports starting/resuming threads, and exposes sandbox presets such as read-only, workspace-write, and full-access.
Source: https://developers.openai.com/codex/sdk

Claude Agent SDK docs show `claude_agent_sdk.query(...)`, `ClaudeAgentOptions`, session resume through `session_id`, MCP configuration, and allowed tool controls.
Source: https://code.claude.com/docs/en/agent-sdk/overview

These shapes imply Vellum should own a provider-neutral session model and adapt Codex/Claude events into one Vellum stream protocol.

## User Experience

### Mode Switch

When the user selects Coding mode:

- The window chrome, sidebar, chat pane, and composer remain in place.
- The workspace side panel opens to a Coding Home state if no project/session is selected.
- The composer shows coding-specific controls:
  - Provider: `Codex` or `Claude Code`.
  - Project folder / cwd.
  - Access: read-only, workspace-write, full-access, ask-every-time where supported.
  - Model/profile only when the selected provider exposes a meaningful choice.

The user should feel that they changed profile, not app.

### Coding Home

If no coding project is active, show a real empty state:

- "Open project folder"
- "Resume recent coding session"
- Provider health row:
  - Codex installed/available
  - Claude Code installed/available
  - Backend connected

No example tasks or decorative fake agents.

### Active Coding Session

Once a project is selected:

- Main chat streams the provider's real assistant response.
- A compact status strip shows provider, cwd, access mode, and session/thread id.
- Right/workspace tabs available:
  - Files: real project tree from backend.
  - Terminal: existing `/api/terminal/ws`.
  - Browser: existing workspace/browser bridge.
  - Run Log: real SDK events and backend lifecycle events.
  - Diff: real file changes only when detected from disk or provider events.

Agent/subagent tabs should not exist in MVP unless backed by real emitted provider activity. If a provider emits subagent-like metadata later, map it then.

### Stop And Resume

The user can:

- Stop a running turn if the SDK adapter supports cancellation or process/session termination.
- Resume a Codex thread id or Claude session id from stored session metadata.
- Continue a session with the same provider, cwd, and access mode by default.

Provider switching mid-session should create a new Vellum coding session linked to the same project. Do not pretend Codex context carries into Claude or the reverse.

## Backend Architecture

Add a focused coding package:

```text
backend/agent/coding/
  __init__.py
  models.py
  service.py
  storage.py
  events.py
  adapters/
    __init__.py
    base.py
    codex.py
    claude.py
```

### Core Types

`CodingSession`

- `id`: Vellum session id.
- `provider`: `codex` or `claude`.
- `provider_session_id`: Codex thread id or Claude session id when available.
- `cwd`: absolute workspace path.
- `title`: derived from first user task or folder name.
- `access_mode`: Vellum access enum.
- `status`: idle, running, stopped, error.
- `created_at`, `updated_at`.

`CodingTurn`

- `id`
- `session_id`
- `prompt`
- `status`
- `started_at`, `completed_at`
- `final_response`
- `error`

`CodingEvent`

- `id`
- `session_id`
- `turn_id`
- `type`
- `message`
- `payload`
- `created_at`

### Provider Adapter Interface

```python
class CodingProviderAdapter(Protocol):
    provider: str

    async def health(self) -> ProviderHealth: ...
    async def start_session(self, request: StartCodingSession) -> ProviderSession: ...
    async def resume_session(self, session: CodingSession) -> ProviderSession: ...
    async def run_turn(self, session: CodingSession, prompt: str) -> AsyncIterator[CodingEvent]: ...
    async def stop_turn(self, session: CodingSession, turn_id: str) -> None: ...
```

Adapters convert provider-specific messages into Vellum `CodingEvent` objects. UI code should never import provider-specific event names.

### Codex Adapter

Dependency: add `openai-codex` to backend dependencies.

Behavior:

- Use `AsyncCodex` for FastAPI compatibility.
- Start a thread with requested sandbox:
  - `read` -> `Sandbox.read_only`
  - `write` -> `Sandbox.workspace_write`
  - `full` -> `Sandbox.full_access`
  - `ask` -> start with safest supported mode for MVP, likely read-only, and expose unsupported status clearly.
- Store the Codex thread id in `provider_session_id`.
- Run prompts on the existing thread.
- Emit at minimum:
  - `session.started`
  - `turn.started`
  - `assistant.delta` if available from SDK streaming
  - `assistant.final`
  - `turn.completed`
  - `turn.error`

If the Python SDK only returns a final result for the first implementation path, emit `assistant.final` and keep the UI honest. Do not fake token streaming.

### Claude Adapter

Dependency: add `claude-agent-sdk` to backend dependencies.

Behavior:

- Use `query(prompt=..., options=ClaudeAgentOptions(...))`.
- Set cwd/project path through the SDK-supported option if available; otherwise launch from a controlled backend working-directory wrapper only if the SDK supports it safely.
- Use `allowed_tools` for MVP access:
  - read-only: read/search tools only.
  - workspace-write: read/search/edit/write plus safe shell only if configured.
  - full: explicit user-enabled setting only.
- Capture `SystemMessage` init `session_id` and store it in `provider_session_id`.
- Resume with `ClaudeAgentOptions(resume=session_id)`.
- Emit `assistant.delta` only if messages arrive incrementally. Otherwise emit real message-level events.

### Storage

Use SQLite under `backend/data/memory/coding_sessions.db`.

Tables:

- `coding_sessions`
- `coding_turns`
- `coding_events`

Store metadata and event payloads. Avoid storing secrets. Do not store environment variables or API keys in event payloads.

### API Routes

Add routes under `/api/coding`.

```text
GET  /api/coding/health
GET  /api/coding/sessions
POST /api/coding/sessions
GET  /api/coding/sessions/{session_id}
POST /api/coding/sessions/{session_id}/turns/stream
POST /api/coding/sessions/{session_id}/stop
GET  /api/coding/sessions/{session_id}/events
GET  /api/coding/projects/tree?root=<path>
GET  /api/coding/projects/recent
```

Streaming route returns SSE. Event names:

- `session`
- `turn`
- `assistant_delta`
- `assistant_final`
- `tool`
- `file_change`
- `error`
- `done`

Use the existing Responses-style event lessons from `/api/chat/stream`, but keep coding events namespaced and provider-neutral.

## Frontend Architecture

The current `vellum-workspace.html` is the visual reference, but the MVP should move the implementation into the real Vellum desktop/frontend code rather than expanding the single-file prototype.

Recommended UI modules:

```text
frontend or desktop app source/
  components/
    workspace/
      VellumWorkspace
      ModeSwitch
      WorkspaceTabs
      Composer
    coding/
      CodingHome
      CodingSessionPane
      CodingStatusStrip
      CodingProviderPicker
      CodingRunLog
      CodingFileTree
      CodingDiffView
  services/
    codingApi
    terminalApi
    workspaceBrowserApi
```

If the MVP must land faster, first copy the prototype's visual CSS/layout into the active frontend, then componentize. Do not keep long-term product logic in `design/Velllum/uploads/vellum-workspace.html`.

### Remove Or Replace From Prototype

Remove from production coding path:

- `MAIN_MSGS`, `RAMAN_MSGS`, static `SUBAGENTS`, fake `TASKS`, fake `FILE_TREE`.
- Browser-side `runCodingTurn`, `planTask`, fake worker/reviewer/synthesis loops.
- Browser-side direct provider calls to OpenRouter/OpenAI for coding mode.
- Any hardcoded model catalog that pretends to be live SDK availability.

Replace with:

- API-driven session list.
- API-driven project tree.
- API-driven provider health.
- SSE-driven coding turns.
- Real terminal and browser routes that already exist.

## Access And Safety

MVP must default to workspace-write or read-only, not full access.

Access policy:

- `read_only`: inspect project files and answer. No writes or shell mutation.
- `workspace_write`: edit inside selected project only. Shell commands require visible terminal/run log and current session permission.
- `full_access`: hidden behind explicit setting. Show clear status when active.
- `ask_every_time`: if provider does not support interactive approvals through the SDK path yet, show "not available in MVP" instead of silently approximating.

Path safety:

- Resolve project cwd before starting sessions.
- Reject paths that do not exist.
- File tree and file reads must stay inside selected project root.
- Do not expose `.env`, credential files, or known secret paths in the file viewer by default.

Secrets:

- Provider API keys stay in existing backend config/environment patterns.
- UI health checks show configured/unconfigured, never the key value.

## Event Mapping

Provider-neutral event contract:

```json
{
  "id": "evt_...",
  "session_id": "code_...",
  "turn_id": "turn_...",
  "provider": "codex",
  "type": "assistant.delta",
  "message": "short human label",
  "payload": {},
  "created_at": "2026-06-05T..."
}
```

Minimum event types:

- `session.started`
- `session.resumed`
- `turn.started`
- `assistant.delta`
- `assistant.final`
- `tool.started`
- `tool.completed`
- `file.changed`
- `turn.completed`
- `turn.error`

Only emit an event when it comes from the provider SDK or a real backend action. If the adapter cannot observe a lifecycle detail, omit it.

## Error Handling

User-facing failures:

- Provider not installed: "Codex SDK is not installed." or "Claude Agent SDK is not installed."
- Provider auth missing: "Provider is not configured."
- Project path invalid: "Project not found."
- SDK start failure: show the SDK error summary and keep session in error state.
- Unsupported streaming: show final response when complete, with status "streaming unavailable".

Do not invent a successful run after a provider error.

## Testing

Backend tests:

- Adapter health reports missing dependencies without crashing.
- Session storage creates, resumes, lists, and persists provider ids.
- Codex adapter maps access modes to sandbox presets.
- Claude adapter captures `session_id` from init messages and resumes with it.
- SSE route emits start, final/error, and done events.
- Project tree endpoint rejects path traversal.

Frontend tests:

- Coding mode empty state renders with no demo data.
- Provider selector populates from `/api/coding/health`.
- Sending a prompt appends streamed real events.
- Stop button calls `/api/coding/sessions/{id}/stop`.
- Files tab renders backend tree and shows empty/error states.

Manual verification:

- Start backend.
- Start desktop app.
- Open Coding mode.
- Select a small local repo.
- Run one Codex turn in read-only mode.
- Run one Claude Code turn in read-only mode.
- Resume each session and ask a follow-up.
- Open Terminal tab and confirm it uses `/api/terminal/ws`.
- Confirm no prototype messages, fake agents, fake diffs, or fake file rows appear.

## Rollout Order

1. Add backend dependencies, provider health checks, and storage.
2. Implement Codex adapter with final-response path first.
3. Implement Claude adapter with message-level streaming/resume.
4. Add `/api/coding/*` routes and tests.
5. Move/copy the workspace visual shell into the active desktop/frontend app.
6. Wire Coding mode to `/api/coding/*`.
7. Replace fake file tree with real project tree.
8. Keep existing terminal/browser tabs wired to current backend endpoints.
9. Remove or quarantine preview-only coding fixtures from production path.

## Non-Goals For MVP

- Background cloud workers.
- Automatic git commit/push.
- Multi-agent delegation UI.
- Review-gate pipelines.
- Synthetic progress when the provider does not expose progress.
- Local model coding assistant.
- Cross-provider shared context.
- A complete redesign of Vellum.

## Open Questions

These are implementation checks, not product blockers:

- Does `openai-codex` expose token/event streaming in the Python API, or only final result for `thread.run` in the current build?
- Which Claude Agent SDK option is the correct cwd/project binding in Python for this repo version?
- Should Vellum run SDK sessions inside the existing backend process, or isolate each turn in a worker process for cancellation and dependency stability?

The implementation plan should answer these with small probes before full wiring.

