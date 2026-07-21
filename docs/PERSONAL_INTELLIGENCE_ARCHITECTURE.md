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
