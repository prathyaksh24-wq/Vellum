# Vellum Automations — Codex-style Cron Scheduling for the Reasoning Agent

**Date:** 03/08/2026
**Status:** Approved design — ready for tickets
**Surface:** `design/Velllum/uploads/Vellum Default Re-designed.html` (served via vite `/design-uploads/`; `frontend/ui/` mirrors)
**Scope owner:** Reasoning (ChatGPT-style chat) agent only. Coding mode and Computer mode untouched. Frontend is the single static HTML + `api/*.js` clients.
**Governs:** `CONTEXT.md` glossary is authoritative for terms used here; resolve older docs (`docs/CLAUDE.md` "Automation & Routines") in favor of this spec.

---

## 1. Purpose

Give Vellum the Codex/OpenAI scheduled-tasks model: a user creates an **Automation**
(recurring or one-shot) either through a chat-guided flow or a manual form, the
scheduler fires it **server-side** while the API process is running, and each
**run** is a full reasoning-agent turn whose results land in a UI feed (standalone)
or an existing pinned conversation.

This replaces the `/api/automations` mock (`backend/agent/api.py:2354`) and the
hardcoded built-in scheduler registration in `start_scheduler()`
(`backend/agent/scheduler/digest.py:96`) — built-ins migrate into the same store.

## 2. Non-goals

- **No changes to the coding mode** (`backend/agent/coding/`), including its
  `ReasoningEffort` enum — untouched.
- No vault write-back of automation output (UI feed / pinned chat only).
- No platform delivery (Telegram/Discord/...). No delivery tokens.
- No pre-check "watchdog" / script-only runs in this phase.
- No separate runner process; APScheduler stays in the API process (which is
  already a detached persistent service via `scripts/start-api.ps1`).
- No changes to existing conversation-library, retention, or privacy subsystems.

## 3. Domain model

See `CONTEXT.md`. Summary of decisions:

| Term | Definition |
|------|-----------|
| Automation | instructions + schedule + destination + model profile + state + permission profile. User-owned, inspectable. |
| Run | one execution; fresh session context; result lands in the destination. `scheduled → running → complete/failed`. |
| Schedule | relative (`30m`), interval (`every 2h`), 5-field cron (`0 9 * * *`), or ISO one-shot. Exactly one per automation. |
| Destination | `new_chat` (fresh conversation per run, results in a Scheduled feed) or `existing_chat` (pinned `thread_id`, each run appends a turn). |
| Model profile | model tier (primary / fast / explicit model id) + reasoning mode. |
| Reasoning mode | `light`/`medium`/`high`/`extra high`/`max`/`ultra` — a NEW core control for the reasoning agent and sub-agents (not just automations). |
| State | automation: `active` / `paused` / `removed`. Run: `scheduled` / `running` / `complete` / `failed`. |
| Permission profile | full-access opt-in per automation, surfaced clearly at creation. |

## 4. Architecture

### 4.1 Store — JSON job store

New module `backend/agent/automations/store.py`:

- File: `data/automations.json` (next to existing store files under `data/`).
- Atomic writes (write temp file + rename) — Hermes-style.
- Records: `{ id, name, instructions, schedule: {kind, expression}, destination: {kind, thread_id?}, model_profile: {tier?, model?, reasoning_mode?}, permission: {full_access: bool}, state: active|paused, builtin: bool, created_at, updated_at, run_history: [...] }`.
- `run_history`: bounded per automation (last ~100 runs), each `{ id, started_at, finished_at, status: running|complete|failed, output?|error? }`.
- API mirrors `BlueprintSuggestionStore` patterns (`backend/agent/skills/suggestions.py`) for load/save conventions.

### 4.2 Schedule parsing

New module `backend/agent/automations/schedules.py`:

- Add `croniter` to `backend/requirements.txt`.
- Parse four formats → canonical record:
  - relative: `30m`, `2h`, `1d` (one-shot; `run_date = now + delta`)
  - interval: `every 2h`, `every 1d at 09:00` (APScheduler `interval` trigger)
  - cron: 5-field (APScheduler `cron` trigger)
  - ISO: `2026-08-03T09:00:00Z` (one-shot)
- Reject unknown formats with a clear error surfaced in UI and agent tool.

### 4.3 Engine — scheduler registration

Refactor `start_scheduler()` (`backend/agent/scheduler/digest.py:96`):

- Built-in jobs (memory_dreaming, nightly_digest, vault_retention,
  youtube_intelligence_projection, skill_curator_tick, plus the api.py
  `scheduled_dreaming` registration at `api.py:709`) migrate into the store as
  `builtin: true` records on first startup (idempotent seeding).
- Built-ins: visible + editable + pausable like user automations, **protected from
  removal** (delete restores the default schedule).
- New `AutomationScheduler` wrapper: on startup, load store → register jobs with
  APScheduler `max_instances=1` + misfire-grace (3600, matching existing jobs);
  on mutation (create/update/pause/delete) re-register the affected job only.
- One run at a time per automation; a fire whose predecessor is still running is
  skipped (matching `max_instances=1` semantics).

### 4.4 Runner — the fired turn

New module `backend/agent/automations/runner.py`:

- Fired job → create run record → execute a **full reasoning turn** via the same
  path interactive chat uses: `agent.ainvoke` with `_thread_config(thread_id)`,
  `model=resolved` (from model profile), message = automation Instructions
  (plus pinned thread's recent context when `existing_chat`).
- **Reasoning mode injection**: the new reasoning-mode control maps to
  provider-level inference parameters (e.g. `reasoning_effort`/token budget on the
  OpenRouter call, routed through `backend/agent/llm/`) — added to the core chat
  path and usable by normal interactive turns too.
- Permission: `full_access` runs bypass ask-every-time gates (documented opt-in);
  default is NOT granted.
- Completion: output (or error) written to `run_history`; for `existing_chat`
  destinations, appended into that conversation's thread (persisted via the
  conversation store); for `new_chat`, surfaced in the Scheduled feed.
- No vault write-back (per non-goals).

### 4.5 API — replace the mock

Replace `@router.get("/automations")` (api.py:2354) with a real CRUD router
(`backend/agent/automations/api.py`, mounted into `api.py`):

- `GET /api/automations` — list (store records + recent runs).
- `POST /api/automations` — create (manual form + agent tool both call this).
- `PATCH /api/automations/{id}` — edit any field (schedule, destination,
  instructions, model profile, state pause/resume).
- `POST /api/automations/{id}/run` — run-now.
- `DELETE /api/automations/{id}` — remove (built-ins → restored, not deleted).
- `GET /api/automations/{id}/runs` — run history.

### 4.6 Agent tool — chat-guided creation

- The reasoning agent gains a `cronjob` action-tool (Hermes-style), usable in any
  reasoning chat: create / update / pause / resume / remove / run-now automations.
- "Create automation" button in the UI opens a new reasoning chat with a
  pre-filled explainer prompt (Codex behavior): the agent drafts instructions,
  proposes a schedule and destination, asks for confirmation, then creates via the
  API.
- The tool reports validation errors back into the conversation.

### 4.7 UI — `Vellum Default Re-designed.html`

- **Automations / Scheduled view**: list automations (name, schedule, destination,
  status), recent runs per automation, run-now, pause/resume, edit, delete.
- **Create**: button → chat-guided flow; form → manual create (all fields).
- **Edit surface**: schedule, destination, model profile (tier + reasoning mode
  picker), instructions, permission toggle (full-access opt-in, prominent).
- Uses existing `api/automations.js` client (extended to the new endpoints).

## 5. Interaction and accessibility

- Reasoning-mode picker: `VSelect`-based (existing component), unique accessible
  labels, keyboard behavior inherited.
- Full-access opt-in is a deliberate confirmation (toggle + warning copy), never
  silently defaulted on.
- API failures (provider error, timeout, validation) surface as failed runs with
  the error visible in the feed/history; never crash the app.

## 6. Verification

- Store: unit tests for atomic read/write, bounded history pruning, built-in
  seeding idempotency, protected-deletion restore.
- Schedules: parse tests for all four formats + rejection of garbage; APScheduler
  trigger mapping.
- Runner: integration-style tests (pattern of `backend/tests/test_digest.py`,
  `test_youtube_intelligence_scheduler*.py`) — fired job produces a run record,
  full-access runs execute, `existing_chat` appends to the pinned thread,
  skip-if-busy concurrency, failed runs recorded.
- API: CRUD tests incl. pause/resume, run-now, built-in delete-restore.
- Agent tool: tool-call tests creating/updating an automation from a chat turn.
- Frontend: `frontend` test runner (`vite test`, `ui/**/*.test.js` convention) for
  the automations client + Scheduled view; rendered QA on the exact design-upload
  URL (`/design-uploads/Vellum%20Default%20Re-designed.html`).
- Reasoning mode: assert the new control flows into the provider call for normal
  chat and automation turns; coding-mode behavior unchanged.
