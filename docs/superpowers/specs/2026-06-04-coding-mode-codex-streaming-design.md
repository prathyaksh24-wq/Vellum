# Coding Mode — Codex-style Live Streaming & Subagent Multiplexing

**Date:** 04/06/2026
**Status:** Approved design — ready for implementation plan
**Surface:** `design/Velllum/uploads/vellum-workspace.html` (the final Vellum frontend preview)
**Scope owner:** Coding mode only (General and Computer modes untouched)

---

## 1. Purpose

Give Vellum's **Coding mode** a faithful re-creation of OpenAI Codex's real-time
streaming architecture: a single multiplexed event pipe carrying `thread / turn /
item` primitives as JSON-RPC 2.0 frames, parallel sub-agents routed by tag, live
per-agent animations, and a final condensing handshake.

When a user opens a new Coding chat they see an **empty progress bar**. When they
give a task, a planner judges complexity. Simple asks stream a single answer.
Complex asks decompose into tasks, each executed by a **real** sub-agent (its own
model call), all multiplexed down one event bus and rendered live.

The leaf token source in the preview is OpenRouter / OpenAI. Those providers do not
speak JSON-RPC, so the orchestrator **wraps** their raw token deltas into Vellum's
Codex-shaped frames. The protocol is real; only the producer changes when the real
backend lands.

## 2. Non-goals

- No changes to **General** mode (stays simple single-stream chat).
- No changes to **Computer** mode (keeps its computer-use overlay).
- No real OS-level container forks or git worktrees in the preview — context
  isolation is per-routing-tag context buckets, not real processes. Real isolation
  is a later backend concern.
- No backend work in this slice. The memory/RAG stack is explicitly parked.
- True mid-token interruption is not possible against OpenRouter; steering is
  approximated (see §6).

## 3. Mode gating

`MODES = general | coding | computer` already exists. Everything in this spec is
gated to `mode === "coding"`:

| Mode | Behavior |
|------|----------|
| General | Existing single-stream chat. No planner, no progress panel, no subagents. |
| Coding | Full system: planner → (simple = single stream) OR (complex = JSON-RPC bus + parallel subagents + plan block + handshake). |
| Computer | Existing overlay flow. Untouched. |

## 4. Protocol — the Vellum streaming schema (Codex-shaped)

A single module (`VProtocol`) defines JSON-RPC 2.0 notification frames. In the
preview these flow through an in-memory bus that yields the identical NDJSON wire
shape; later the same frames arrive over SSE/WebSocket from FastAPI.

### Primitives
- **thread** — a chat (`chatId`).
- **turn** — one user submission's full execution (`turnId`).
- **item** — a unit inside a turn: a plan, a subagent, an agent message, reasoning,
  or a tool call.

### Frames (JSON-RPC notifications, `{"jsonrpc":"2.0","method":..,"params":..}`)
| Method | Params (key fields) | Meaning |
|--------|--------------------|---------|
| `turn/started` | `threadId, turnId` | A submission began executing. |
| `item/plan` | `turnId, complex, reason, tasks[]` | Master's decomposition. `tasks[]` = `{ id, title, role }`. |
| `item/subagent/started` | `turnId, routingTag, persona{name,sprite,color,role}, task` | A subagent spawned for a task. |
| `item/agentMessage/delta` | `routingTag, text` | A token delta from that subagent. |
| `item/reasoning/delta` | `routingTag, text` | Optional intermediate reasoning delta. |
| `item/subagent/completed` | `routingTag, status, output` | Subagent finished (`done`/`error`). |
| `turn/steer` | `threadId, turnId, text` | Client → orchestrator: mid-turn user input. |
| `turn/completed` | `turnId, finalItemId` | Final handshake — condense view. |

### Routing tags (multiplexing)
Every `item/*` frame carries
`routingTag = "agent:<parentId>:subagent:<uuid>"`.
The master orchestrator uses `agent:master:turn:<turnId>` for its own synthesis
item. The UI **demuxes** by routing tag into per-agent buckets, which is what
prevents context pollution / "context rot" on the main loop.

## 5. Orchestration flow (Coding mode, on submit)

```
user submits ─▶ turn/started
                 │
                 ▼
        Planner call (master, non-streaming, low temp)
        returns { complex, reason, tasks[] }   ── tolerant JSON parse
                 │
        ┌────────┴─────────┐
   complex:false       complex:true
        │                  │
   single stream      item/plan  ──▶ render inline plan block + side panel tree
   (existing chat)         │           (all tasks pending, bar = 0%)
        │                  ▼
        │        for each task (PARALLEL, capped at 5):
        │           item/subagent/started (assign persona from SUBAGENTS pool)
        │           worker model call ─▶ item/agentMessage/delta* (wrapped)
        │           [optional] reviewer model call ─▶ reasoning/delta* (gate)
        │           item/subagent/completed
        │                  │
        │                  ▼  (all tasks done)
        │        Synthesis call (master) ─▶ agentMessage/delta* into main message
        │                  │
        └──────────────────┴─▶ turn/completed  ──▶ final handshake (condense)
```

- **Planner** decides complexity from the actual prompt. Cap: **≤ 5 tasks**.
- **Workers** run in **parallel**, each a real scoped model call (overall goal + its
  one task + relevant shared context). Their OpenRouter SSE deltas are wrapped into
  `item/agentMessage/delta` frames tagged with the subagent's routing tag.
- **Reviewer** (optional, default on, toggleable): a second persona streams a
  compliance/quality gate per task into `item/reasoning/delta`.
- **Synthesis**: master takes all task outputs + original request and streams the
  consolidated answer into the main chat message the user reads.

## 6. Steering (`turn/steer`)

While a turn runs, the composer stays active. Submitting text emits `turn/steer`.
Since OpenRouter cannot be interrupted mid-token, the orchestrator approximates:
abort the targeted (or most-recent) subagent stream and re-issue it with the steer
text appended to its context. Faithful at the event level (`turn/steer` exists and
is honored), best-effort at the token level. Documented as a known preview limit.

## 7. UI / state

### State (per chat, alongside `msgs` / `threadRef`)
```js
progress[chatId] = {
  status: 'idle'|'planning'|'running'|'done'|'error',
  turnId, reason,
  tasks: [{ id, title, status:'pending'|'running'|'review'|'done'|'error',
            routingTag, persona, output, reviewerVerdict? }]
}
```
New chat → `{ status:'idle', tasks:[] }`.

### Rendering
- **Single bus subscriber** per thread. A reducer consumes frames and updates
  `progress[chatId]` + per-subagent streamed text (demuxed by routing tag).
- **Inline plan block** (chat stream): compact, Codex-style; steps `○ → ⋯ → ✓`;
  the active subagent named under the running step ("Faraday is working").
- **Side Progress panel**: slim determinate **progress bar** (`done/total`, 0% on
  new chat), task tree, subagent roster. Reuses `openSubagent()` to open a
  subagent's streamed output in a tab. Sits above existing **Outputs** / **Sources**.
- **Empty state**: panel shows the bar at 0% + "No tasks yet" (mirrors existing
  `No artifacts yet` / `No sources yet`).
- **Per-agent animation**: reuse existing `.streaming-text` glow + caret, keyed per
  routing tag, while that agent's deltas flow.
- **Final handshake**: on `turn/completed`, expanded subagent streams collapse into
  the single consolidated answer to keep the primary view tidy.

### Removed / repurposed
- The scripted `MAIN_MSGS` multi-agent demo is **removed** so Coding chats start
  empty. The `SUBAGENTS` array survives as the **persona pool** the orchestrator
  assigns from (name / sprite / color / role).
- The current "new chat auto-opens Progress with static content" is replaced by the
  empty-state panel.

## 8. Swap-to-real seam

The UI subscribes **only** to the bus. The producer is the only thing that changes:

- **Now (preview):** `InMemoryProducer` runs the orchestration (§5) and emits frames.
- **Later (backend):** `SseProducer` reads identical JSON-RPC frames over
  SSE/WebSocket from FastAPI. No UI or reducer changes.

One `runTask(task, ctx, emit)` function isolates "do a task" so the leaf call
(OpenRouter today, real agent later) is swappable without touching multiplexing or
UI.

## 9. Errors

- Planner unparseable or `complex:false` → fall back to existing single stream.
- A worker/reviewer call fails → that task `error`; siblings continue; synthesis
  notes the gap; progress bar still completes (errored tasks counted as resolved).
- No API key / network error → existing error surface; turn ends `error`.

## 10. Testing / verification

This is the single-file HTML preview; verification is:
1. **JSX compiles** — validate via the existing esbuild check (`frontend/node_modules/esbuild`).
2. **Manual run-through** in browser:
   - General mode: unchanged single-stream chat.
   - Coding + simple ask ("rename a var"): single stream, panel stays empty.
   - Coding + complex ask ("build a CLI todo app with tests"): plan block appears,
     ≥2 subagents stream in parallel with glow + names, bar fills, reviewer gates,
     final handshake condenses to one answer.
   - Steer mid-turn: text is accepted and reflected.
   - New chat: empty progress bar, "No tasks yet".

## 11. Open items deferred to backend phase

- Real SSE/WebSocket JSON-RPC server in FastAPI emitting these frames.
- True container/worktree isolation for parallel agents.
- Shared TypeScript/Python schema generation from the protocol contract.
