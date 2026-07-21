# Vellum Personal Intelligence Architecture

This document defines the migration from an Obsidian-centered knowledge system
to a local-first, Cerebras-style evidence architecture. The migration is
additive: existing conversations, memory, retrieval, plugins, skills, and wiki
behavior remain available until their replacement path has reached parity.

## Outcome

Vellum continuously learns from approved conversations, books, X archives,
YouTube activity, sports, connector data, and tool observations. Learning means
updating inspectable evidence, entities, claims, temporal preferences, and
retrieval context. It does not mean silently fine-tuning model weights.

```text
Sources and tools
  -> privacy and consent policy
  -> immutable source versions
  -> entities, observations, and claims
  -> temporal preference model
  -> retrieval indexes and context packs
  -> chat, coding, specialists, frontend, and Obsidian projections
```

## Ownership

| Concern | Current owner during migration | Target owner |
| --- | --- | --- |
| Conversations | `data/ui/conversations.json` | Knowledge Core after verified cutover |
| Active thread state | LangGraph checkpoints | LangGraph checkpoints |
| Durable personal memory | Memory Orchestrator SQLite | Memory Orchestrator SQLite |
| User model | Honcho | Honcho, fed only approved derived signals |
| Raw source evidence | `Vault/Library` and legacy source folders | Knowledge Core source records and blobs |
| Maintained wiki | `Vault/Knowledge` | Karpathy-style Obsidian projection |
| Human-readable conversations | `Vault/Agent/Conversations` | Obsidian projection |
| Keyword and semantic indexes | FTS5 and Chroma | Rebuildable indexes |
| Skills | Hermes `SKILL.md` packages | Hermes `SKILL.md` packages |

The Memory Orchestrator remains the application coordinator. The Knowledge Core
does not replace Honcho, FTS5, Chroma, or the resolved-answer cache; it gives
them one evidence and provenance boundary.

## Storage

Desktop mode uses SQLite for identity, provenance, policy, temporal state, and
lineage. Large source bodies are gzip-compressed, content-addressed blobs under
`data/knowledge/blobs/`. Duplicate content is stored once. Database and blob
paths are runtime data and are excluded from Git.

The initial schema includes:

- sources and immutable source versions
- entities, aliases, and relationships
- observations and promotion status
- claims and claim evidence
- user signals and temporal preference states
- derived insights
- projection records with `do_not_reingest`
- connector cursors and ingestion jobs
- bounded context packages

## Ingestion Control Plane

Every connector run uses an account-scoped idempotency key and an ingestion job
record. Successful completion and cursor advancement occur in one transaction;
a failed run records a bounded error code and leaves the previous cursor intact.
Repeating a completed or in-flight idempotency key does not execute the provider
operation again. This contract is shared by scheduled and user-triggered runs.
Failed jobs can retry the same key, and expired running leases can be reclaimed;
attempt counts remain visible for diagnosis.

The frontend receives read-only job and cursor health. Connector execution stays
inside trusted backend adapters; the browser cannot claim provider identity or
advance a sync cursor.

A future hosted deployment may use PostgreSQL and object storage behind the
same service contract. Desktop operation must not require users to administer
those services.

## Migration Modes

The default migration state is shadow mode:

```text
KNOWLEDGE_CORE_ENABLED=true
KNOWLEDGE_SHADOW_WRITE=true
KNOWLEDGE_READ_ENABLED=false
KNOWLEDGE_TOOL_OBSERVATION_LEARNING=false
```

Shadow writes are best-effort and cannot fail an existing memory write. Reads
continue through the established Memory Orchestrator and Knowledge Wiki until
retrieval evaluations, privacy checks, and count reconciliation pass.

## Existing Data Adapters

The bootstrap API previews by default. Applying it is explicit and repeatable.

- Conversations become private-local source records with content-addressed versions.
- `Library/` notes become raw source records according to folder policy.
- `Knowledge/` pages are imported as legacy maintained evidence and registered as projections.
- `Agent/Conversations` and `Agent/Memories` are registered as projections only.
- Notes marked `do_not_reingest` never become independent evidence.

No adapter deletes, renames, or rewrites existing files.

## Observation Semantics

Every observation records its initiator:

- `user`: direct user behavior or instruction
- `agent`: an agent-selected tool call
- `scheduled`: policy-bound refresh work
- `connector`: provider events and synchronization
- `imported`: historical archive material

Agent and scheduled searches can refresh knowledge, but they cannot reinforce a
user preference merely because Vellum chose to run them. Preferences must be
supported by user behavior, explicit confirmation, or a separately approved
policy.

When `KNOWLEDGE_TOOL_OBSERVATION_LEARNING=true`, the shared `ToolRegistry`
captures successful read results after capability and profile permission checks.
X posts and YouTube metadata/transcripts become versioned source evidence;
unknown tools produce metadata-only observations. Observer failure never changes
the tool result, and this path never writes `user_signals` directly.

## Books

Raw book pages are `private_local_only` and `deny_raw`. They may be parsed,
indexed, and analyzed locally. External context packages can contain only
approved, privacy-safe derivatives and citations; raw pages are withheld.
Page, chapter, edition, OCR confidence, and interpretation classification must
remain attached to every derived claim.

## Temporal Preferences

Preferences are evidence-backed state, not timeless labels. Each signal has a
stable event key, actor, source, evidence class, sensitivity, value, weight, and
timestamp. Only approved user, connector, and imported activity is eligible;
agent and scheduled actions are retained for provenance but excluded from the
preference calculation.

The public frontend endpoint accepts only `actor=user`. Connector and imported
signals enter through trusted backend adapters so a browser client cannot forge
provider history.

Each subject retains its historical peak alongside a freshness-adjusted current
score, 30-day and prior-window summaries, trend, lifecycle, confidence, and last
meaningful engagement. A channel can therefore move from `active` to `waning`,
`occasional`, or `dormant` without losing the fact that it was historically
important. Explicit negative feedback can move a subject to `rejected`.

## Sensitive Context and Interpretation

Retention is separate from endorsement. Political posts, protected-class humor,
sexual content, harassment, violence, health, financial material, and ambiguous
engagement can remain searchable evidence while being excluded from preference
and style learning. Each annotation records labels, context, stance, intent,
confidence, taxonomy version, eligibility, and review state.

Likes, bookmarks, timelines, reposts, quotations, and agent-selected searches do
not prove agreement. They default to `stance=unknown`; passive signal weight is
capped, and sensitive evidence requires trusted user review before it can affect
preference or humor/style behavior. No content is deleted merely because it is
sensitive.

## Context Packs

Chat, coding, and specialists consume bounded context packages instead of
reading storage engines directly. A context package declares purpose,
destination, token budget, source filters, freshness, and citation policy.
External packages never include `deny_raw` content or local machine paths.

## Frontend Contract

The canonical frontend is:

`design/Velllum/uploads/Vellum Default Re-designed.html`

It accesses Personal Intelligence only through `window.VellumApi.knowledge`
and versioned `/api/knowledge/*` endpoints. Storage schema and file layout are
not frontend contracts.

Initial additive endpoints:

- `GET /api/knowledge/core/status`
- `GET /api/knowledge/core/ownership`
- `GET /api/knowledge/core/sources`
- `GET /api/knowledge/core/observations`
- `POST /api/knowledge/core/signals`
- `GET /api/knowledge/core/preferences`
- `GET /api/knowledge/core/ingestion-jobs`
- `GET /api/knowledge/core/sync-cursors`
- `GET /api/knowledge/core/annotations`
- `POST /api/knowledge/core/context-packs`
- `POST /api/knowledge/core/bootstrap`

The existing wiki endpoints remain stable throughout migration.

## Cutover Gates

Canonical ownership moves only after all gates pass:

1. Repeated imports create no duplicate sources or versions.
2. Conversation, source, and projection counts reconcile.
3. Private book and feedback content cannot enter external context packs.
4. Projection exports cannot be reingested.
5. OAuth revocation and source deletion propagate through derived records.
6. Backup and restore are verified.
7. FTS and vector indexes rebuild from canonical records.
8. Retrieval evaluation meets or exceeds the existing system.
9. The frontend reports honest loading, empty, stale, and failure states.

Old writers are retired separately after a stable read cutover. Existing files
are not deleted as part of the ownership change.

## Migration Operations

The operational CLI is preview-first and prints structured JSON:

```powershell
.venv\Scripts\python.exe scripts\knowledge_core.py status
.venv\Scripts\python.exe scripts\knowledge_core.py bootstrap
.venv\Scripts\python.exe scripts\knowledge_core.py backup --output data\knowledge\backups\before-bootstrap.zip
.venv\Scripts\python.exe scripts\knowledge_core.py verify data\knowledge\backups\before-bootstrap.zip
```

Applying the existing-data bootstrap requires the literal confirmation token:

```powershell
.venv\Scripts\python.exe scripts\knowledge_core.py bootstrap --apply --confirm APPLY_KNOWLEDGE_BOOTSTRAP
```

Backups use SQLite's online backup API, include content-addressed blobs and a
checksummed manifest, and are verified before the command succeeds. Restore is
not automated yet; it remains a cutover gate until atomic restore and rollback
tests are implemented.
