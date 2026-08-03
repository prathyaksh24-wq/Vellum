# CONTEXT.md — Vellum Glossary

> Shared vocabulary for Vellum's domain model. Glossary only — no implementation details.

This file holds the agreed vocabulary across design workstreams. Resolve conflicts with older docs (e.g. `docs/CLAUDE.md` "Automation & Routines") in favor of this file.

## Glossary

### YouTube channel entity
One local canonical entity keyed by an official YouTube channel ID.

### Channel alias
A title observed for that same channel ID, preserved so renames do not create a second local entity.

### Identity collision candidate
A normalized alias linked to distinct channel IDs. It is a review item, not an instruction to merge.

### Cross-channel merge
Combining two distinct external channel IDs. This is deferred and never automatic in the current scope.

### Automation
A recurring or one-shot rule that launches an agentified run on a schedule. An automation has **instructions** (what the agent does each run), a **schedule** (when), a **destination** (where results land), a **model profile** (which model / reasoning), and a **state** (active/paused, etc). Synonyms people use: scheduled task, cron job, route. On Vellum these are user-owned and inspectable.

### Run
A single execution of an Automation, fired by the scheduler at a schedule's next fire-time. Runs are isolated (fresh session context) and produce results in the Automation's destination.

### Schedule
The timing rule of an Automation — how often / when a run fires. Expressible as a relative delay (`30m`), an interval (`every 2h`), a 5-field cron expression (`0 9 * * *`), or a specific ISO timestamp. An Automation has exactly one schedule.

### Destination
Where a run's results are delivered. Two flavours, matching the Codex scheduled-tasks model:

- **New chat (standalone)** — each run happens in a fresh conversation, independent of other runs. Results collect in a "Scheduled" / automations view.
- **Existing chat** — the automation is pinned to one ongoing conversation (`thread_id`); each run appends a turn/channel into that conversation, preserving its context.

Run results are delivered to the UI surface (standalone feed or pinned conversation) only. Vellum is vault-first but automation output is **not** written to the Obsidian vault for this feature.

### Scheduler residency
Codex-style **server-side**: the scheduler lives in the backend API process (uvicorn, detached via `scripts/start-api.ps1` — already a persistent service independent of the desktop app/UI). Automations fire whenever the API service is running, even with the UI closed. On startup the store reloads and jobs re-register; missed runs follow APScheduler misfire-grace behavior (catch-up) like today's built-ins.

### Instructions
The natural-language prompt describing what the agent should do each time an Automation runs. What an agent executes per run.

### Model profile
The set of model + reasoning choices for an Automation's runs (which model tier, which reasoning mode). Editable after creation.

### Reasoning mode
A per-turn control (Codex-style) deciding how much inference effort the agent spends: `light`, `medium`, `high`, `extra high`, `max`, `ultra`. Applies to the **reasoning chat agent**, **sub-agents**, and **Automations**. Not present in Vellum today (the **coding** mode has a separate, narrower `ReasoningEffort` and is **out of scope** — do not modify the coding mode). This work adds the reasoning-mode control to the core reasoning/chat agent path.

### Model tier
Which running model an Agent turn uses: **primary** (default), **fast** (cheap/summarising), or an explicit provider/model id. Automations can pin a tier or an exact model; unset means the global primary.

### State
An Automation is **active** (scheduled to run), **paused** (kept, not running), or **removed** (gone). A run is **scheduled → running → complete/failed**.

### Run history and concurrency
Codex-matching semantics: the Scheduled view shows **recent runs** (bounded — e.g. last ~100 per automation; older runs are pruned/archived, not deleted forever by user intent). **One run at a time per automation** — a run whose predecessor is still active is skipped (not queued), mirroring the existing `max_instances=1` + misfire-grace behavior of built-in jobs.

### Unattended permissions
Automation runs fire with no human watching. Each Automation carries a permission profile chosen at creation: **full access opt-in** (user explicitly grants unrestricted execution) is the supported mode; the UI surfaces this clearly at creation time.
