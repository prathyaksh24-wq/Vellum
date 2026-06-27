# Emulated Coding-Assistant IDE — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build `design/Velllum/uploads/vellum-coding.html` — a self-contained, offline, web-previewable desktop-app preview of Vellum's coding-assistant mode that emulates the Codex and Claude Code SDKs.

**Architecture:** Single HTML file, React 18 + Babel-standalone (CDN), no backend/network. A built-in `SAMPLE_PROJECT` repo + `CODING_SCENARIOS` drive a deterministic `runEmulatedCodingTurn` scheduler that streams provider-dialect events into chat + Run Log + Files + Diff + Terminal. Desktop chrome (titlebar + sidebar) styled like `vellum-workspace.html`.

**Tech Stack:** React 18, Babel JSX, `setTimeout`-based event scheduling, `crypto.randomUUID`. Verification: esbuild compile gate + manual browser run-through.

**Testing note (adapted):** single-file embedded React, no unit runner. Each task verifies with (a) `node design/Velllum/uploads/check-coding.mjs` → `OK: JSX compiles`, and (b) manual browser checks where observable. Non-`OK` compile = hard failure.

---

## File map
| File | Responsibility | Action |
|------|----------------|--------|
| `design/Velllum/uploads/vellum-coding.html` | The entire preview app | Create |
| `design/Velllum/uploads/check-coding.mjs` | esbuild JSX compile gate for the new file | Create |

---

## Task 1: Scaffold + compile gate
**Files:** Create `vellum-coding.html`, `check-coding.mjs`.
- [ ] HTML boilerplate: React 18 + ReactDOM + Babel CDN, `<div id="root">`, `<script type="text/babel" data-presets="react">`.
- [ ] Base CSS: dark theme vars, window chrome (`.win`, `.titlebar`, window controls), `.sidebar` (New chat / Search / Plugins / Projects / Chats), `.main`, layout grid. Mirror palette from `vellum-workspace.html` (#0d0d0d bg, ember #e35d2b, Geist/system font).
- [ ] `I` icon wrapper + a handful of icons (IcFolder, IcFile, IcTerminal, IcGlobe, IcTasks, IcPlay, IcStop, IcSend, IcChevR, IcCheck, IcCircle, Spinner).
- [ ] `App` skeleton: titlebar + sidebar + main placeholder ("Coding Home goes here"). `ReactDOM.createRoot(...).render(<App/>)`.
- [ ] `check-coding.mjs`: same as `check-jsx.mjs` but targets `vellum-coding.html`.
- [ ] Verify: `node design/Velllum/uploads/check-coding.mjs` → `OK: JSX compiles`. Commit + push.

## Task 2: Sample repo + scenarios data
**Files:** Modify `vellum-coding.html`.
- [ ] `SAMPLE_PROJECT`: `{ name:'todo-cli', files:[ {path, content} … ] }` with `cli.py`, `core.py`, `storage.py`, `tests/test_core.py`, `README.md`, `requirements.txt` — each with short real-looking content.
- [ ] Helper `fileTree(files)` → nested tree for the Files tab.
- [ ] `CODING_SCENARIOS`: array of `{ id, match:(task)=>bool, steps:[ {delay, kind, label, payload} ] }` for add-a-flag, fix-a-bug, write-a-test + `GENERIC_SCENARIO`. `kind` ∈ `reasoning|read|edit|cmd|out|final`. `payload` carries file path, diff hunks, terminal text, prose.
- [ ] `pickScenario(task)` → first matching scenario else generic.
- [ ] Verify compile. Commit + push.

## Task 3: Coding Home state
**Files:** Modify `vellum-coding.html`.
- [ ] State: `session` (null = Home), `provider` ('codex'|'claude'), `recents` (emulated list).
- [ ] `CodingHome` render: title, **provider picker** (Codex / Claude Code segmented), **provider health row** (Codex available · Claude Code available · Backend preview-mode), **Open project** (opens `todo-cli`; optional real folder-attach input), **Resume recent session** list.
- [ ] `openProject(proj)` → builds a new `session` object (see state shape in spec §8), sets `cwd`, `sessionId` (`thread_…` or `sess_…` per provider), `accessMode='workspace-write'`, `status:'idle'`.
- [ ] Verify compile + manual: Home renders, picker toggles, no fake agents. Commit + push.

## Task 4: Active session shell (chat + status strip + composer)
**Files:** Modify `vellum-coding.html`.
- [ ] When `session` set, render the IDE layout: left = chat pane + composer; right = workspace tab bar (Files/Terminal/Browser/Run Log/Diff) with a body placeholder.
- [ ] `StatusStrip`: provider · cwd · access mode pill (elevated style for full-access) · session id.
- [ ] Composer: textarea + coding controls (provider readonly indicator, access-mode dropdown), Send/Stop button. `onSubmit(task)` → appends a user message + calls the emulator (Task 5).
- [ ] Chat message list renders user + assistant messages (assistant supports streaming text).
- [ ] Verify compile + manual: open project → session shell shows, status strip correct. Commit + push.

## Task 5: Emulator engine
**Files:** Modify `vellum-coding.html`.
- [ ] `newSessionId(provider)`, `dialect(provider)` → maps generic `kind` to provider-flavored event label (Codex: `tool: apply_patch`, `thread.started`, `command: exec`; Claude: `tool_use: Edit`, `system.init`, `tool_use: Bash`).
- [ ] `runEmulatedCodingTurn(task)`: pick scenario, set `status:'running'`, then for each step `await sleep(step.delay)` and apply it — push an event (dialect-labeled) to `session.events`, and depending on `kind`: stream assistant prose (chat), mark `edited[path]`, push diff hunks, append terminal lines. End `assistant.final` → set `finalText`, `status:'done'`, push `turn.completed`.
- [ ] Cancellation: a `cancelRef`; Stop sets it; the loop checks and aborts → `status:'idle'` + a "stopped" event.
- [ ] Use React state setters immutably (clone session, update, setSession). Guard against stale closures with a ref to the live session.
- [ ] Verify compile + manual: submit a task → events stream over ~6–10s, chat fills, status flips running→done. Commit + push.

## Task 6: Workspace tabs
**Files:** Modify `vellum-coding.html`.
- [ ] `FilesTab`: render `fileTree`; click file → show content (monospace); edited files show an ember dot.
- [ ] `TerminalTab`: render `session.terminal` lines (`$ cmd` ember prompt, output gray, monospace).
- [ ] `BrowserTab`: simple URL bar + placeholder "localhost:8000" page card (static).
- [ ] `RunLogTab`: `session.events` list — each row: time, type badge (colored per kind), label. Auto-scroll to newest.
- [ ] `DiffTab`: render `session.diffs` — file header + hunks with `+`/`−`/context line coloring.
- [ ] Tab bar switches active tab; default to Run Log while running, Diff when done.
- [ ] Verify compile + manual: each tab shows real emulated content during/after a run. Commit + push.

## Task 7: Wire-through, provider distinctiveness, polish
**Files:** Modify `vellum-coding.html`.
- [ ] Confirm Codex vs Claude produce visibly different Run Log vocabularies for the same task.
- [ ] Access-mode dropdown affects the emitted sandbox/permission label; full-access shows elevated pill.
- [ ] "New chat"/back returns to Coding Home; Resume recent rebuilds a session with prior provider/cwd.
- [ ] Empty/honesty states: "Backend: preview mode" visible; fix-a-bug shows failing→passing.
- [ ] Final full manual run-through (spec §10): both providers, all tabs, access modes, resume.
- [ ] Verify compile. Commit + push.

---

## Self-review
- Spec §4 (Home/Active) → Tasks 3,4. §5 emulator → Task 5. §6 tabs → Task 6. §7 sample+scenarios → Task 2. §8 state → Tasks 3–6. §9 honesty → Tasks 4,6,7. §10 testing → compile gate + manual each task. ✓
- No placeholders; data shapes (`session`, scenario `step {delay,kind,label,payload}`, `dialect`) are consistent across Tasks 2,5,6. ✓
- Names stable: `runEmulatedCodingTurn`, `pickScenario`, `dialect`, `SAMPLE_PROJECT`, `CODING_SCENARIOS`, `session`, `openProject`. ✓
