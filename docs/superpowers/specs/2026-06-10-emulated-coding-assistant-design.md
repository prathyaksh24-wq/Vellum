# Emulated Coding-Assistant IDE (Codex + Claude Code) — Preview

**Date:** 10/06/2026
**Status:** Approved design — ready for implementation plan
**Surface:** NEW standalone file `design/Velllum/uploads/vellum-coding.html` (separate from `vellum-workspace.html`)
**Nature:** Front-end preview only. No Tauri, no backend, no API keys, no network. Fully self-contained, web-previewable.

---

## 1. Goal

A convincing, self-contained **desktop-app preview** of Vellum's coding-assistant mode that
**emulates** the OpenAI Codex SDK and the Claude Code (Claude Agent) SDK. Opening a project and
typing a coding task plays a realistic, deterministic, offline run — the assistant "thinks",
calls tools, edits files, runs terminal commands, and produces a diff — streamed into an
IDE-style workspace. Nothing is wired to a real backend; everything is emulated in-file.

This reuses the UX of the approved real-MVP spec
(`2026-06-05-coding-assistant-sdk-mvp-design.md`) but swaps "real backend" for "emulation".

## 2. Non-goals

- No Tauri packaging (previewable as a plain `.html` in a browser).
- No real backend, SDK, OpenRouter, or network calls. No API keys.
- No real file writes — the "project" is an in-memory sample repo (a real client-side
  folder-attach may be offered as a non-essential bonus, still no backend).
- Not a modification of `vellum-workspace.html` — this is a separate file.

## 3. Shell

Self-contained desktop-app chrome (titlebar + window controls + left sidebar), styled to match
the Vellum dark aesthetic from `vellum-workspace.html`. The coding-assistant IDE is the main
content. Default look = the Windows/desktop chrome. (No shell switcher needed; this file is the
desktop coding preview.)

## 4. Two states

### 4.1 Coding Home (no active session)
A real empty state — no decorative fake agents/tasks:
- **Open project** → pick a built-in **sample repo** (`todo-cli`, ships in-file). Optional
  client-side real folder-attach as a bonus.
- **Resume recent session** → emulated recent-sessions list (provider · cwd · relative time).
- **Provider health row** → Codex: *available* · Claude Code: *available* · Backend: *preview mode*.
- **Provider picker** → `Codex` ⟷ `Claude Code`.

### 4.2 Active session (project selected)
- **Chat pane** streams the emulated provider assistant reply.
- **Status strip:** provider · cwd · access mode · session/thread id.
- **Composer coding controls:** provider, project/cwd, access mode
  (`read-only` / `workspace-write` / `full-access`).
- **Workspace side tabs:** Files · Terminal · Browser · Run Log · Diff.

## 5. The emulated SDK run (core)

`runEmulatedCodingTurn(task, provider, access)` schedules a timed, believable event sequence
(via `setTimeout`/async steps) that streams into all surfaces at once, with the task text woven
in. Deterministic and offline.

**Provider dialects** (each feels distinct):

- **Codex** (JSON-RPC flavor): `thread.started (sandbox: <access>)` → `reasoning…` →
  `tool: read_file` → `tool: apply_patch (+N −M)` → `command: exec $ pytest` →
  `assistant.final` → `turn.completed`. IDs like `thread_a1b2c3`. Access → sandbox preset
  (`read_only` / `workspace_write` / `full_access`).
- **Claude Code** (Agent-SDK flavor): `system.init (session_id)` → assistant message →
  `tool_use: Read` → `tool_use: Edit` → `tool_use: Bash` → `tool_result` → `assistant.final`.
  IDs like `sess_x9y8z7`. Access → `permission_mode`.

The single event stream drives: **chat** (assistant prose), **Run Log** (timestamped feed),
**Files** (edited files badged), **Diff** (the patch), **Terminal** (commands "run").

## 6. Workspace tabs (all emulated)

- **Files** — the sample repo tree; click a file → its content; edited files get a dot badge.
- **Terminal** — the commands the run "executed" (`$ pytest` → passing output), styled like a
  real terminal (monospace, prompt).
- **Browser** — a simple emulated browser tab (URL bar + placeholder page) for local-dev feel.
- **Run Log** — the provider-neutral event stream with type badges + timestamps. Replaces the
  old subagent progress panel for coding mode.
- **Diff** — unified diff of the run's changes, against real-looking sample-repo paths
  (green `+` / red `−` lines, file headers).

## 7. Sample repo + scenarios

**`SAMPLE_PROJECT`** — a small built-in Python CLI repo `todo-cli`:
```
todo-cli/
  cli.py        (argparse entry; the most-edited file)
  core.py       (TodoStore: add/list/done)
  storage.py    (json persistence)
  tests/test_core.py
  README.md
  requirements.txt
```
Each file has short, real-looking content so Files/Diff/Terminal read authentically.

**`CODING_SCENARIOS`** — 3 templated runs chosen by task keywords, plus a generic fallback:
1. **add-a-flag** (keywords: add/flag/option/json/output) → edits `cli.py` (+ a few lines),
   runs `python cli.py --json`, shows the diff.
2. **fix-a-bug** (keywords: fix/bug/error/crash) → reads + patches `core.py`, runs `pytest`,
   shows a failing→passing transition.
3. **write-a-test** (keywords: test/coverage/pytest) → adds `tests/test_cli.py`, runs `pytest`,
   shows the new file + diff.
4. **generic fallback** → reads 1–2 files, makes a small edit to the most relevant file,
   runs `pytest`, summarizes.

Each scenario is a list of timed steps `{ delay, kind, payload }` rendered through the active
provider's dialect, so the same scenario looks Codex-flavored or Claude-flavored.

## 8. State + modules (isolation)

```js
codingSession[chatId] = {
  provider:'codex'|'claude', cwd, accessMode, sessionId, status:'idle'|'running'|'done'|'error',
  events:[ {id,t,kind,label,payload} ],
  edited:{},          // path -> true
  diffs:[ {path, hunks:[{old,new,lines:[{type:'ctx'|'add'|'del', text}]}]} ],
  terminal:[ {type:'cmd'|'out', text} ],
  finalText:''
}
```

New in-file modules (each focused): `SAMPLE_PROJECT`, `CODING_SCENARIOS`, `emulator` (the
`runEmulatedCodingTurn` scheduler + provider dialect mapper), and render blocks
`CodingHome`, `StatusStrip`, `FilesTab`, `TerminalTab`, `BrowserTab`, `RunLogTab`, `DiffTab`.

## 9. Errors / honesty

- Access `full-access` shows a clear "elevated" status pill.
- If a scenario "fails" (fix-a-bug first run), the failing test output is shown before the fix —
  not hidden. The run ends in a clear `done` or `error` state; no fake "success after error".
- "Backend: preview mode" is shown plainly so it's never mistaken for a live integration.

## 10. Testing / verification

Single-file HTML preview — verification is:
1. **Compile gate** — a `check-jsx.mjs`-style esbuild check on the new file
   (`node design/Velllum/uploads/check-coding.mjs` → `OK: JSX compiles`).
2. **Manual run-through** in a browser:
   - Coding Home renders with provider health + no demo agents.
   - Open the `todo-cli` sample → active session, status strip shows provider/cwd/access/session id.
   - Submit "add a --json flag" with **Codex** → Codex-dialect events stream into Run Log, chat
     prose streams, `cli.py` badged in Files, Diff tab shows the patch, Terminal shows the command.
   - Switch provider to **Claude Code**, submit "write a test for core" → Claude-dialect events
     (`tool_use: Read/Edit/Bash`), new test file appears, diff + terminal update.
   - Access = `full-access` shows the elevated pill.
   - Resume a recent session from Coding Home.

## 11. Out of scope (explicit)

Real SDKs, real backend, Tauri, network, real file writes, multi-agent orchestration, git
commits. Those belong to the real MVP (`2026-06-05` spec), not this preview.
