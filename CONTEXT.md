# CONTEXT.md — Vellum Glossary

> Shared vocabulary for Vellum's domain model. Glossary only — no implementation details.

This file holds the agreed vocabulary across design workstreams. Resolve conflicts with older docs (e.g. `docs/CLAUDE.md` "Automation & Routines") in favor of this file.

## Glossary

### Workspace Layout
The device-local, persistent selection and arrangement of Vellum application surfaces. The user can reveal, hide, or arrange surfaces through App Actions; a layout with no optional surfaces shows only the natural-language input, without becoming a separate application mode. Existing users and first launch begin with Vellum's current complete layout, which remains unchanged until the user customizes it.
_Avoid_: Agent Mode, Full Mode, UI mode

### UI Surface
A registered visual region or control with a stable identity and an allowlisted set of configurable properties, such as visibility, placement, size, label, theme, or density. A UI Surface may be owned by Vellum or contributed by a plugin; App Actions never rewrite arbitrary DOM, CSS, or frontend code.
_Avoid_: DOM node, Arbitrary component

### UI Customization
A device-local override to an allowlisted UI Surface property. It persists across application restarts until changed or reset; a session-only override exists only when the user explicitly requests temporary behavior.
_Avoid_: CSS override, Theme hack

### Adaptive UI
Vellum's ability to learn from prior user behavior and proactively apply reversible Workspace Layout or presentation changes. An explicit "always" instruction creates a rule immediately; otherwise Vellum requires three consistent repetitions in the same context. Inferred rules begin at the narrowest relevant agent, project, device, or window context and become global only through explicit instruction or repeated evidence across contexts. The first automatic application explains what changed and offers Undo and "Don't learn this"; undoing it counts as negative evidence and suppresses the rule. Learned rules are inspectable, disableable, and removable through natural language and an optional settings surface. Adaptive UI never performs data, privacy, plugin-lifecycle, external, or destructive actions without current user intent.
_Avoid_: Proactive agent action, Autonomous application control

### UI Reference
The stable identity used to target a UI Surface through natural language or direct interaction. A reference may resolve from an explicit name, current selection or focus, or a single unambiguous visible match; Vellum asks for clarification when multiple surfaces match.
_Avoid_: DOM selector, Screen coordinate

### Control Kernel
The irreducible Vellum surfaces required to issue, approve, and recover from App Actions: the natural-language input, destructive-action confirmation, error and recovery feedback, and Workspace Layout reset. Control Kernel surfaces cannot be disabled, removed, or owned by optional plugins.
_Avoid_: Core UI, Default layout

### Plugin Contribution
A UI Surface or App Action registered through Vellum's shared contribution interface by either an optional built-in feature or a third-party plugin. Built-in contributions ship enabled and may be hidden but are protected from accidental uninstall; Control Kernel surfaces are not Plugin Contributions.
_Avoid_: Hard-coded panel, Plugin-specific UI path

### App Action
A named semantic operation that changes Vellum application, session, or presentation state and can be invoked through either natural language or a visual control. A visible visual control remains interactive and dispatches the same App Action as its natural-language equivalent. Every conversation resolves actions from the current enabled catalog, so newly enabled or disabled Plugin Contributions take effect in past, present, and future chats. Natural-language App Actions execute only after explicit submission, never from partially typed input. Safe or reversible actions execute immediately with Undo; destructive, irreversible, privacy-changing, or external actions require explicit confirmation even under full access.
_Avoid_: UI click, DOM action, Agent command

### Action Parity
The requirement that every visual control which changes meaningful Vellum state dispatches a registered App Action that is also available through natural language. Non-state gestures such as scrolling, selecting text, or focusing an input are exempt.
_Avoid_: Click automation, Best-effort NLP support

### Conversation Turn
A normal user-agent exchange that follows Vellum's existing conversation, retrieval, memory, source, and history behavior. A Conversation Turn remains distinct from an App Action; adding natural-language interface control does not replace or fork the existing conversation path. One submitted request may contain both: safe App Actions execute alongside the conversational answer, while destructive actions wait for confirmation without blocking that answer.
_Avoid_: Interface command, App Action

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
