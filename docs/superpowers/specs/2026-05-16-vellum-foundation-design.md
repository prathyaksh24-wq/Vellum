# Vellum Foundation — Meta + Projects vault restructure & ProjectContext loader

**Status:** Draft for review
**Created:** 16/05/2026
**Author:** Vellum (brainstormed with user)
**Slice of:** "Agent that knows me, thinks like me, acts like me, predicts" — Foundation slice (1 of N)

---

## 1. Purpose

Vellum today is a privacy-first RAG agent over an Obsidian vault. It retrieves notes, runs tools, calls OpenRouter, and writes outputs to `Agent/`. What it does **not** do is hold an always-on model of *who the user is* and *what work is currently active*.

This slice adds that layer. It is the foundation every later slice (voice-and-style, thinking-tools, identity-memory-v2, proactive observer) depends on.

After this slice ships:

- Vellum reads three small identity files (`Meta/profile.md`, `goals.md`, `principles.md`) into every system prompt — unconditional identity.
- Vellum supports a per-thread "active project" concept; when set, it also loads that project's charter (`vellum.md`) and rolling context (`hot.md`).
- Vellum maintains two files inside the active project: `hot.md` (rewritten periodically) and `log.md` (appended per turn).
- The existing vault folders (`X/`, `Youtube/`, etc.) move under a new `Library/` parent to make the four roles — identity, work, reference, agent state — visually obvious.

This slice does **not** ship any "thinking like you" or "speaking like you" behavior. Those are subsequent slices that consume this foundation.

---

## 2. Goal of the parent project (context only)

The user's stated end goal is a deeply personal agent that knows them, thinks like them, speaks like them, and predicts intent without explanation. This was decomposed during brainstorming into four slices:

1. **Foundation** (this spec) — vault restructure + identity files + ProjectContext loader.
2. **Voice & Style** — corpus of the user's writing + speak-like-me prompt + style eval.
3. **Thinking Tools** — `/context`, `/trace`, `/emerge`, `/graduate` slash commands.
4. **Identity Memory v2** — continuously distilled self-model note.

Each slice gets its own spec → plan → implementation cycle.

---

## 3. Decisions made during brainstorming

These are the closed questions; everything else in this spec follows from them.

| # | Decision |
|---|----------|
| D1 | Primary identity raw material: **vault notes + every chat with Vellum** (Honcho + `Agent/Responses`). No external feeds in scope. |
| D2 | Behavior model: **layered** — reactive (default), proactive (via scheduler), autonomous (per-project, gated by `vellum.md`). This slice ships only the structure; behavior comes in later slices. |
| D3 | First slice to design and ship: **Foundation** (this spec). |
| D4 | `Meta/` contents: `profile.md`, `goals.md`, `principles.md`. **No** daily notes. |
| D5 | Each `Projects/<slug>/` contains: `vellum.md`, `hot.md`, `log.md`, `notes/`. |
| D6 | Active project resolution: **per-thread**, set on thread start, switchable via `/project <slug>` chat command. |
| D7 | Existing folders move into a new `Library/` parent; `Agent/` stays where it is. |
| D8 | `profile.md` v1 is **user-authored from an empty template** Vellum drops in. No agent-drafted bootstrap. |
| D9 | Loader architecture: **preamble injection** (option A). Single new module reads files and prepends to system prompt. |
| D10 | Date format throughout Vellum vault files and templates: **DD/MM/YYYY** (and `DD/MM/YYYY HH:MM` in `log.md`). Overrides existing CLAUDE.md ISO convention for new files. Machine-only logs (`audit_log.jsonl`) keep ISO. |
| D11 | `hot.md` user-edit guard: Vellum stamps a content hash; on mismatch, append a `## Hot (vellum proposed, DD/MM/YYYY HH:MM)` section rather than overwrite. |
| D12 | Privacy: Meta/Projects content is scrubbed through the existing Presidio pipeline before injection into any OpenRouter call. The user's real name lives in `profile.md`; OpenRouter sees `[PERSON]`; the local de-anonymizer restores it before display. |

---

## 4. Vault layout (target)

```
Vellum/Vault/
├── Meta/                          ← identity layer, always loaded
│   ├── profile.md                 ← user-authored
│   ├── goals.md                   ← user-authored
│   └── principles.md              ← user-authored
│
├── Projects/                      ← work layer, per-thread active
│   └── <project-slug>/
│       ├── vellum.md              ← user-authored charter
│       ├── hot.md                 ← Vellum-maintained, ~200 tok, rewritten
│       ├── log.md                 ← Vellum-maintained, append-only
│       └── notes/                 ← mixed authorship, indexed normally
│
├── Library/                       ← reference material, agent read-only
│   ├── X/                         ← was Vault/X/
│   ├── Youtube/                   ← was Vault/Youtube/
│   ├── Books/                     ← was Vault/Books/ (if exists)
│   ├── Sports/                    ← was Vault/Sports/ (if exists)
│   ├── Claude code/               ← was Vault/Claude code/
│   ├── Codex/                     ← was Vault/Codex/
│   └── feedback/                  ← was Vault/feedback/ (stays PRIVATE)
│
└── Agent/                         ← Vellum's working memory, unchanged
    ├── Queries/  Responses/  Memories/  Connections/
    ├── Reflections/  Digests/  Skills/  Saved/
```

Four top-level folders, four roles: identity, work, reference, agent state.

---

## 5. File templates

### 5.1 `Meta/profile.md`

User-authored. ~300-600 tokens. Loaded every turn.

```markdown
---
type: meta-profile
updated: DD/MM/YYYY
---
# Profile

## Name
[your real first name; scrubbed to [PERSON] before any LLM call, restored on display]

## Role
[what you do, day-to-day]

## Strengths
- ...

## Weaknesses
- ...

## Communication Style
[blunt? terse? formal? Concrete examples of how you'd want a reply phrased.]

## Pet Peeves
- [things Vellum should never do — e.g., "don't apologize", "don't summarize what you just did"]

## Decision Style
[how you make calls — gut, data-driven, slow-to-commit, reversible-first, etc.]
```

### 5.2 `Meta/goals.md`

User-authored. ~200-400 tokens. Loaded every turn.

```markdown
---
type: meta-goals
updated: DD/MM/YYYY
---
# Goals

## Active
- **<goal>** — deadline: DD/MM/YYYY — shipped looks like: [one sentence]
- ...

## Backlog
- ...

## Sunset
- ...
```

### 5.3 `Meta/principles.md`

User-authored. ~200-400 tokens. Flat bullet list. Loaded every turn.

```markdown
---
type: meta-principles
updated: DD/MM/YYYY
---
# Principles

- One sentence per principle.
- Operating beliefs, mental models, decisions you've already made.
- ...
```

### 5.4 `Projects/<slug>/vellum.md`

User-authored. ~400-800 tokens. Loaded when project is active.

```markdown
---
type: project-charter
slug: <slug>
status: active | paused | done
created: DD/MM/YYYY
---
# <Project Name>

## Goal
[one paragraph — what success looks like]

## Vellum's Role
[reactive only? autonomous writes allowed in notes/? can draft external content?]

## Definition of Done
- ...

## Allowed Actions
- read: notes/, Library/
- write: notes/, hot.md, log.md
- forbid: anything outside this project folder

## Open Questions
- ...
```

### 5.5 `Projects/<slug>/hot.md`

Vellum-maintained. ~200 tokens hard target. Rewritten every N turns (default 5) or on `/end`. Loaded when project is active.

```markdown
---
type: project-hot
updated: DD/MM/YYYY HH:MM
turn_count: <N>
---
# Hot

**Last touched:** [files/notes]
**Open threads:** [unresolved questions or in-flight work]
**Last decision:** [what was concluded last session]
**Next:** [what comes next, if known]

<!-- vellum-managed: <sha256 of body above this line> -->
```

### 5.6 `Projects/<slug>/log.md`

Vellum-maintained. Append-only. Not loaded into prompt; audit only.

```markdown
- DD/MM/YYYY HH:MM · [session|auto] · <one-line summary> · turn=<thread_id-turn>
- DD/MM/YYYY HH:MM · [session]       · drafted X · turn=<id>
```

---

## 6. Data flow per turn

```
USER QUERY
   │
   ├── PrivacyGate (existing) → classified + scrubbed
   │
   ▼
ProjectContext.build(thread_id)             ← NEW
   1. Read Meta/profile.md, goals.md, principles.md (always)
   2. Look up sessions.active_project for thread_id
   3. If set: read Projects/<slug>/vellum.md + hot.md
   4. Run Presidio scrubber over the assembled IDENTITY block
   5. Wrap in <PROTECTED>…</PROTECTED> tags (per CLAUDE.md §1 stage 3)
   6. Cache in-process for 60s, keyed by (thread_id, mtime of each source file)
   │
   ▼
System prompt assembly in agent/graph/agent.py — strict order:
   ┌──────────────────────────────────────────┐
   │ 1. <PROTECTED> IDENTITY block </PROTECTED>│ ← prepended (new)
   │ 2. Honcho user context                    │ ← existing
   │ 3. Operational contract (from CLAUDE.md)  │ ← existing
   │ 4. Skill instructions if matched          │ ← existing — may reference items 1-3
   └──────────────────────────────────────────┘
   Ordering matters: skills (4) load LAST so their instructions can reference identity
   from (1) — e.g., a "speak-like-me" skill can say "use the Communication Style block
   above" and have it already be in context.
   │
   ▼
LangGraph ReAct loop (existing) → tools, retrieval, response
   │
   ▼
store_response (existing)
   │
   └── ProjectContext.tick(thread_id, turn_summary)   ← NEW
         1. Append one line to Projects/<slug>/log.md
         2. Increment in-memory turn counter for this thread
         3. If counter % N == 0 OR thread terminated:
            a. Read recent turns from LangGraph checkpointer
            b. Summarize via fast model (Gemma 4 12B) — see §7
            c. Verify hot.md content-hash matches expected (user-edit guard)
            d. Either rewrite hot.md or append proposed section
            e. Reset in-memory counter
```

---

## 7. Components

All paths relative to `Vellum/backend/agent/`.

### 7.1 `memory/project_context.py` (new)

Public surface:

- `ProjectContext.build(thread_id: str) -> str` — returns the scrubbed, tagged IDENTITY block ready for prepending to the system prompt. Empty string if `Meta/` missing.
- `ProjectContext.tick(thread_id: str, turn_summary: str) -> None` — appends to `log.md`; may trigger `hot.md` rewrite.
- `ProjectContext.set_active_project(thread_id: str, slug: str | None) -> None` — writes to `sessions.active_project`. `None` clears.
- `ProjectContext.get_active_project(thread_id: str) -> str | None`.

Internal:

- File reads use the existing `obsidian/vault.py` helpers (don't reinvent path handling).
- Token counting via the same tokenizer used elsewhere in `agent/usage/`.
- Hard-truncate at per-file token budgets (profile 600, goals 400, principles 400, vellum 800, hot 200), append `[truncated]`.
- In-process cache: `dict[(thread_id, frozenset((path, mtime))) -> str]`, TTL 60s.

### 7.2 `obsidian/folder_policy.py` (amended)

New entries; old `X/`, `Youtube/`, `Books/`, `Sports/`, `Agent/` rules move under their new `Library/` paths verbatim.

| Path | Indexed | Sent to LLM | Agent writable |
|---|---|---|---|
| `Meta/` | yes | yes | **no** |
| `Projects/<slug>/vellum.md` | yes | yes (when active) | **no** |
| `Projects/<slug>/hot.md` | yes | yes (when active) | **yes, rewrite-only** |
| `Projects/<slug>/log.md` | no | no | **yes, append-only** |
| `Projects/<slug>/notes/` | yes | yes (when active) | **yes** |
| `Library/X/` | yes | yes | no |
| `Library/Youtube/` | yes | yes | no |
| `Library/Books/` | yes | **no** (PRIVATE) | no |
| `Library/feedback/` | yes | **no** (PRIVATE) | no |
| `Library/Sports/` | yes | yes | no |
| `Library/Claude code/` | yes | yes | no |
| `Library/Codex/` | yes | yes | no |
| `Agent/` | (existing rules) | (existing) | (existing) |

Active-project gating (both directions) is enforced by `ProjectContext`, not by `folder_policy`:

- folder_policy answers the static question "is this path in principle readable/writable/sent-to-LLM?"
- `ProjectContext` answers the dynamic question "is this path the *currently active* project's file for this thread?"

So `folder_policy` declares `Projects/<any>/hot.md` writable in principle; `ProjectContext` refuses any write whose `<slug>` doesn't match the thread's `active_project`. Same for read-into-prompt: folder_policy says yes-in-principle, `ProjectContext` restricts to the active slug.

### 7.3 Sessions table extension

`Vellum/backend/agent/memory/sessions.py` already maintains a sessions store. Add two columns:

```sql
ALTER TABLE sessions ADD COLUMN active_project TEXT NULL;
ALTER TABLE sessions ADD COLUMN turns_since_hot_rewrite INTEGER NOT NULL DEFAULT 0;
```

`turns_since_hot_rewrite` lives in the database (not in-process) so that multi-worker FastAPI deployments and process restarts don't lose the count. `ProjectContext.tick()` increments this column inside the same transaction as the `log.md` append; when it reaches `HOT_REWRITE_EVERY_N_TURNS` (default 5), the rewrite runs and the counter resets to 0.

Migration script ships with the slice.

### 7.4 Chat commands

Wired into the TUI command router and the web command parser:

- `/project <slug>` — sets `active_project` for current thread; validates that `Projects/<slug>/vellum.md` exists.
- `/project --clear` — sets `active_project = NULL`; thread runs in Meta-only mode.
- `/project` (no args) — prints current active project and a list of available ones. Discovery is `glob("Vault/Projects/*/vellum.md")` — any directory with a `vellum.md` is a project; presence of `vellum.md` is what makes a project a project.
- `/project create <slug>` — creates `Vault/Projects/<slug>/` with `vellum.md` (from template in §5.4), `hot.md` (empty body + hash comment), `log.md` (empty), `notes/` (empty); then sets `active_project = <slug>` on current thread; refuses if `<slug>` already exists.

Slug rules: lowercase letters, digits, hyphens; 2-40 chars; regex `^[a-z][a-z0-9-]{1,39}$`. Validation rejects invalid slugs before any disk write.

### 7.5 Migration script `scripts/migrate_vault_v2.py` (new)

Dry-run by default; `--apply` to execute.

Phases:

1. Create `Vault/Meta/`, `Vault/Projects/`, `Vault/Library/`.
2. Drop starter templates into `Vault/Meta/` (empty `profile.md`, `goals.md`, `principles.md` from §5).
3. Move existing reference folders into `Library/`.
4. Update `folder_policy.py` (code generation step or manual diff — actually applied to source, not at runtime).
5. Rebuild Qdrant collection (full reindex; folder paths in metadata changed). **Expect this to take 5-30 minutes on a sizable vault** (rough order: a few seconds per 100 chunks at typical embedding throughput). Migration script prints progress every 100 chunks. Migration can be interrupted and resumed; reindex is restart-safe (idempotent upsert by chunk id).
6. Rebuild FTS5 index from `Agent/Responses/`.
7. Rewrite wikilinks in all `Vault/**/*.md`:
   - `[[X/...]]` → `[[Library/X/...]]`
   - `[[Youtube/...]]` → `[[Library/Youtube/...]]`
   - (etc. for each moved folder)
   - Must handle four Obsidian link forms: plain `[[link]]`, aliased `[[link|alias]]`, header `[[link#heading]]`, and embed `![[link]]` (and combinations, e.g. `![[link#heading|alias]]`).
   - Must skip fenced code blocks (```` ``` ````) and inline code (`` ` ``).

Safeguards:

- Backup tarball at `Vellum/data/backups/vault-pre-v2-DD-MM-YYYY.tar.gz` before any move.
- Git working-tree check; aborts if dirty unless `--allow-dirty`.
- Dry-run prints every action; nothing touches disk without `--apply`.
- Idempotent: re-running with `--apply` is a no-op if the structure is already migrated.

---

## 8. Error handling

| Failure | Response |
|---|---|
| `Meta/profile.md` missing | Log warning, proceed with empty IDENTITY block. Do not crash. |
| `Meta/` entire folder missing | Empty IDENTITY block. Audit-log entry `meta_missing`. Degraded mode. |
| Active project set but `vellum.md` missing | Clear `active_project` on session, log warning, fall back to Meta-only. |
| Any source file exceeds token budget | Truncate at budget, append `[truncated]`, log warning with overflow size. |
| `hot.md` user-edit detected on rewrite (sha mismatch OR missing `<!-- vellum-managed -->` comment entirely) | Append `## Hot (vellum proposed, DD/MM/YYYY HH:MM)` below user edits. Do **not** overwrite. Prepend a `⚠ hot.md has your edits; I appended a proposed update at the bottom.` line to the next assistant response. |
| Active `active_project` slug folder renamed or deleted between turns | Detect on next `build()` (missing `vellum.md`); clear `active_project` on the thread; surface `⚠ project <slug> not found; cleared.` on next response. |
| Migration script crash mid-execution (after backup tarball written) | Restore from tarball; safe because Phase 2 moves run after Phase 1 creates + Phase 0 backs up. Re-run with `--apply` is idempotent. |
| Concurrent migration runs | File lock at `Vellum/data/.migration.lock`; second runner exits immediately with `migration in progress`. |
| Vault on multiple machines via Git sync writing to same `hot.md` | Out of scope. Documented limitation: run Vellum on one machine at a time per vault. Future slice may add per-machine project sub-slugs. |
| `log.md` write fails (disk full, perms) | Skip silently; do not block the response; record in audit log. |
| Two threads with same `active_project` writing concurrently | File lock on `hot.md` rewrite (via `portalocker` or equivalent); `log.md` append is atomic via `O_APPEND`. |
| Presidio scrubber errors on IDENTITY block | Block the entire turn (per existing CLAUDE.md §8 — "Withheld."). |
| Cache lookup race during file write | Cache invalidates by mtime; worst case is one stale read; safe. |

Failure messages remain one word where possible, per the existing CLAUDE.md §8 convention.

---

## 9. Privacy

- The IDENTITY block is built locally from local files.
- Before injection into any OpenRouter call, it passes through `agent/privacy/scrubber.py` (Presidio). Real name → `[PERSON]`, email → `[EMAIL]`, location → `[LOCATION]`, etc.
- The full IDENTITY block is wrapped in `<PROTECTED>…</PROTECTED>` tags (CLAUDE.md §1 stage 3).
- `data_collection: deny` continues to apply to every OpenRouter call (CLAUDE.md §6).
- The session-local `[PERSON] → real name` mapping is held in memory only and discarded at session end.
- Responses returning `[PERSON]` are de-anonymized before display, by the existing pipeline.
- `Library/Books/` and `Library/feedback/` remain PRIVATE: indexed locally for retrieval scoring but content never sent to LLM, matching the existing rule from CLAUDE.md §1 stage 4.

---

## 10. Token budget

| Source | Budget | Notes |
|---|---|---|
| `Meta/profile.md` | 600 | hard truncate |
| `Meta/goals.md` | 400 | hard truncate |
| `Meta/principles.md` | 400 | hard truncate |
| `Projects/<slug>/vellum.md` | 800 | hard truncate; only when active |
| `Projects/<slug>/hot.md` | 200 | hard truncate; only when active |
| **Total when no project active** | **~1.4k** | always present |
| **Total when project active** | **~2.4k** | always present |

`hot.md` rewrites are summaries produced by the fast model; the summary prompt instructs ≤200 tokens output.

---

## 11. Testing

Tests in `Vellum/backend/tests/`.

| Unit under test | Cases |
|---|---|
| `ProjectContext.build()` | empty Meta → empty block; full Meta no project → identity-only; full Meta + active project → both; active project missing `vellum.md` → falls back, clears active; file exceeds budget → truncated marker; cache hit on unchanged mtime; cache miss on changed mtime. |
| `ProjectContext.tick()` | appends one `log.md` line with correct DD/MM/YYYY HH:MM; rewrites `hot.md` after `HOT_REWRITE_EVERY_N_TURNS` turns (default **5**, env-overridable); sha mismatch → proposal section appended, not overwrite; writes to wrong slug's `hot.md` rejected (active-project gate). |
| `folder_policy` (amended) | each row in §7.2 table has a positive and negative test. Writes to `Meta/` blocked; writes to inactive project's `hot.md` blocked; writes to active project's `notes/` allowed. |
| Migration | idempotent on re-run; dry-run prints without touching disk; wikilink rewrite handles `[[link]]` and `[[link|alias]]` and skips code blocks; backup tarball created before any move. |
| Privacy integration | `profile.md` with real name → `[PERSON]` in OpenRouter payload (mock); response containing `[PERSON]` → de-anonymized before display. |

Out of scope for this slice's tests: `/context`, `/trace`, `/emerge`, `/graduate`; voice/style behavior; proactive observer.

---

## 12. Backlog (out of scope for Foundation)

Captured here so we don't lose them:

- **`/profile-suggest`** — Vellum proposes additions to `profile.md` based on chat patterns. (User declined the auto-bootstrap option; this is the deferred hybrid.)
- **`/context`, `/trace`, `/emerge`, `/graduate`** — Thinking-Tools slice.
- **User-writing corpus + voice eval** — Voice-and-Style slice.
- **Self-model distillation note** — Identity-Memory-v2 slice.
- **Daily notes** under `Meta/daily/` — user opted out; revisit if a journaling habit forms.
- **`hot.md` write cadence** is hard-coded to 5 turns; consider making it adaptive (token-pressure aware) later.
- **Per-project skill scoping** — restrict which skills load when a given project is active.

---

## 13. Audit findings applied

Brainstorm-phase audit (9 lenses) ran after user verbal approval, before plan. Findings applied to this spec:

- Turn counter moved from in-process to `sessions.turns_since_hot_rewrite` column (multi-worker safe).
- Added `/project create <slug>` command and project-discovery rule (glob `Projects/*/vellum.md`).
- Added slug validation regex.
- Added handling for: missing `<!-- vellum-managed -->` comment, renamed/deleted active project folder, migration partial failure, concurrent migration runs.
- Documented multi-machine Git-sync race as a known out-of-scope limitation.
- Made system-prompt assembly order explicit (identity first, skills last, so skills can reference identity).
- Added Qdrant reindex time-cost note to migration.

## 14. Open issues

None blocking.
