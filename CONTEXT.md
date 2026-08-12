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

## Books Intelligence

### Books Intelligence
The Vellum domain that turns books and reading activity into inspectable book knowledge and personalized relevance.
It excludes general-purpose memory and knowledge from other source domains.

### BooksAgent
The specialist agent that owns book understanding, retrieval, and recommendations.
The main Vellum agent delegates book work to BooksAgent instead of consuming book skills directly.

### Library
A user's collected Book works for which Vellum has an installed Book asset or a usable Book skill.
Discovery recommendations never appear in the Library until one of those conditions is met.

### Discovery
Books, authors, ideas, and relationships proposed for exploration but not installed in the Library.
Discovery metadata and covers do not imply ownership, full-text access, or user endorsement.

### Wisdom
Private, personalized interpretations that connect book evidence to a user's current context, changing interests, and expressed needs.
Wisdom is not part of the reusable book reference corpus.

### Book work
The primary Library identity for a book, independent of a particular publication, translation, revision, or file format.
One Book work appears once on the user's shelf.

### Book edition
Internal provenance for a materially distinct publication, translation, revision, abridgement, or annotated version of a Book work.
Vellum derives it from imported source metadata and content; it stays hidden unless the distinction affects reading or answers.

### Book asset
An exact imported or ingested file associated with a Book edition and identified by its file hash.
EPUB is preferred; multiple Book assets do not create duplicate Book works or duplicate knowledge.

### Book skill
A stable, versioned, navigable representation of book knowledge compiled from the preferred Book asset for a materially distinct Book edition.
BooksAgent consumes Book skills; rebuilding one does not create another Library entry or a general main-agent skill.

### User book state
The private relationship between one user and a Book work. Collection status, interest, and overall opinion belong to the work; progress belongs to the internal edition; exact highlights and annotations retain asset locations plus normalized anchors.

### Wisdom intervention
A proactive, evidence-backed message that BooksAgent surfaces because book knowledge is relevant to the user's current context.
It remains distinguishable from the book's claims and from the user's own beliefs.

### Source class
The permission assigned to a Books provider action: metadata discovery, preview access, rights-cleared ingestion, user import, or prohibited automation.
A provider may support more than one class, but each operation receives exactly one class.

### Rights-cleared ingestion
Automatic installation of full text whose provider supplies an applicable public-domain, open-license, or user-authorized rights basis.
Unknown, conflicting, or region-inapplicable rights metadata never qualifies.

### User import
An explicit local EPUB selection made under the user's accepted rights attestation.
Vellum records import provenance but does not investigate the file's origin.

### Rights receipt
The immutable acquisition evidence for an automatically installed Book asset: provider, source, rights basis, license, region, policy version, retrieval time, metadata snapshot, and file hash.

### Library availability
The user's current access state for a Library entry: Ready, Reading available, Knowledge available, or Processing.
It determines whether Vellum can read the asset, answer through a Book skill, or is still compiling one.
