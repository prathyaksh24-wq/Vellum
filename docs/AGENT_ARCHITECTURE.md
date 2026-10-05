# AGENT_ARCHITECTURE.md
> System configuration and stack for Vellum.
> Read this alongside SOUL.md, CLAUDE.md, and BRAND.md.
> This is the source of truth for how all parts of the system connect.

> Skills architecture update (2026-07): `SKILLS_SYSTEM.md` is authoritative for
> procedural memory. Legacy JSON skill examples below are historical only. Runtime
> definitions are Hermes `SKILL.md` packages indexed by `data/skills/catalog.db`
> and all mutations use the approval coordinator.

---

## The Stack at a Glance

```
┌─────────────────────────────────────────────────────────────────────┐
│                          USER INTERFACES                            │
│                                                                     │
│   Web UI (Vellum.html)     Web/API surfaces             CLI         │
│   Direction A design       Backend endpoints            Fallback    │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│                         AGENT CORE                                  │
│                                                                     │
│   LangGraph StateGraph (model/tool loop when supported)              │
│   Compact prompt + runtime model and specialist directory           │
│   SqliteSaver checkpointer (thread persistence)                     │
│   Matched main skills (specialist skills remain profile-scoped)      │
│   Core tools + deferred capability discovery                        │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
┌────────▼────────┐   ┌──────────▼──────────┐  ┌────────▼────────┐
│  PRIVACY LAYER  │   │    MEMORY SYSTEM     │  │  INFERENCE      │
│                 │   │                      │  │                 │
│ Classifier      │   │ Short-term:          │  │ Provider routing│
│ Presidio scrub  │   │   SqliteSaver        │  │ Ollama / cloud  │
│ <PROTECTED> tag │   │                      │  │                 │
│ Folder policy   │   │ Long-term:           │  │ Gemma 4 31B     │
│                 │   │   Honcho (Docker)    │  │ Qwen 3.5 35B    │
└────────┬────────┘   │   FTS5 (Docker)      │  │ Gemma 4 12B     │
         │            │   Resolved Q cache   │  └────────┬────────┘
         │            │                      │           │
         │            │ Procedural:          │           │
         │            │   .skills/ directory │           │
         │            └──────────┬───────────┘           │
         │                       │                       │
┌────────▼───────────────────────▼───────────────────────▼────────────┐
│                        KNOWLEDGE LAYER                               │
│                                                                      │
│   Obsidian Vault (source of truth — all Markdown, your machine)      │
│   ├── X/            (public — indexed + sent to LLM + tools)        │
│   ├── Youtube/      (public — indexed + sent to LLM + tools)        │
│   ├── Books/        (conditional — Books egress policy)             │
│   ├── feedback/     (private — indexed only)                        │
│   ├── Sports/       (accessible — indexed + sent to LLM)            │
│   └── Agent/        (agent writes — indexed + sent to LLM)          │
│                                                                      │
│   Qdrant (Docker) — vector embeddings, invisible to user            │
│   BGE-M3 (local HuggingFace) — embedding model, runs offline        │
│   Cross-encoder (local) — reranking model, runs offline             │
│   Graph retriever — wikilink-aware retrieval alongside vectors      │
└─────────────────────────────────────────────────────────────────────┘

────────────────────────── DOCKER SERVICES ──────────────────────────

  honcho          → localhost:8001   (user modeling API)
  honcho-deriver  → internal only    (background model updates via Ollama)
  honcho-db       → internal only    (pgvector backing Honcho)
  honcho-cache    → internal only    (Redis work queue/cache)
  sqlite          → data/memory/     (checkpoints, FTS5, resolved cache)

  All Docker volumes and Honcho model calls are local.
  Honcho data persists in honcho_data Docker volume.

─────────────────────── DEVELOPER TOOLING ───────────────────────────

  Graphify    → /graphify . in Claude Code (build sessions only)
                Maps codebase into queryable knowledge graph.
                No runtime role. Not used by the agent.

```

---

## 1. Interfaces

### Default Vellum Streaming Contract

The active frontend surface is
`design/Velllum/uploads/Vellum Default Re-designed.html`.
`design/Velllum/uploads/vellum-workspace.html` is the separate coding workspace,
not the default Vellum frontend. Retired chat HTML files are not targets for new work.

Default Vellum reasoning mode consumes `POST /chat/stream` as
`text/event-stream`. The stream emits OpenAI Responses-style semantic events:

- `response.created`
- `response.in_progress`
- `response.output_item.added`
- `response.output_text.delta`
- `response.output_item.done`
- `response.completed`
- `error`

During migration the backend also emits the older compatibility events `meta`,
`activity`, `tool`, `source`, `token`, and `final`. New UI code should prefer
Responses-style events and treat legacy events as fallback only.

Coding mode is separate: its Codex-style JSON-RPC/event-bus protocol is scoped
to the Coding assistant mode and is not the default Vellum reasoning stream.

### Web UI
- **File:** `Vellum.html` (standalone, no build step required)
- **Design:** Direction A — Pure Stillness (see `DESIGN.md`)
- **Connects to:** FastAPI backend at `http://localhost:8000`
- **State:** Threads, model selection, faculty toggles persist in FastAPI session


### CLI (fallback)
- **File:** `agent/cli.py` (Rich-based, simple)
- **Launch:** `python -m agent.cli`
- **Use when:** Direct terminal chat is needed without a UI shell.
- **Connects to:** Same agent backend


---

## 2. Agent Core

### Framework
The main agent uses a manual LangGraph `StateGraph` with a model node and a
tool node. The tool loop is compiled only when the selected model supports tool
calls. `search_my_notes`, `web_search`, and `delegate_to_agent` are the core
entry points; less common general capabilities are discovered through
`tool_search` and invoked through `tool_call`.

### System Prompt Location
`backend/agent/graph/agent.py` — the provider-neutral `VELLUM_SYSTEM_PROMPT`
constant and dynamic `vellum_prompt` builder. Each turn adds the runtime date and
selected model, thread identity and relevant memory, a compact specialist
directory, and only query-matched main-agent skill instructions.

The system prompt is versioned in git. It is never modified by the agent.
Changes to the system prompt are made by the user, deliberately, in the file.

### Skill Loading
The main agent activates only packages matched to the current user request.
Packages owned by specialist profiles are excluded from that activation and from
the main agent's skill-list and skill-view tools. During a specialist run, the
active profile policy limits skill discovery to that profile's allowlist.
Instructions are loaded for the current task and do not persist across turns.

### Profile-Based Specialist Delegation

Every specialist is a first-class agent with a persistent profile and ephemeral
delegation runs. A profile owns the agent's instructions, allowed tools,
Hermes-compatible skills, private memory scope, shared-memory policy, cache policy,
delegation policy, model or deterministic executor, and response schema.

`AgentCatalog` is the single owner of profiles and runtime executors. It loads
strict version-2-or-newer profiles from `data/agent_profiles/`, applies safe built-in
fallbacks, contains instruction paths, exposes redacted diagnostics, and binds
the current Browser, Music, X, YouTube, Memory, Sports, Books, Discord and Calendar executors to their
profiles. There is no parallel pupil or delegation registry.

The process-wide accessor in `agent/master/live_runtime.py` supplies the same
catalog and runtime to the API and main-model agent tools. Test-local dispatchers
may create an uncached runtime, but they still enter through `DelegationRequest`.

`agent/master/runtime.py` accepts only a typed `DelegationRequest` and creates a
fresh `DelegationRunResult` for every task. It resolves the complete profile and
executor from `AgentCatalog`, enforces delegation admission and depth, and applies
the profile tool policy for the run. Deterministic profiles receive only the
current goal through `answer(query)`. LLM profiles receive profile instructions
plus a bounded task packet containing the goal, explicit context, and
profile-approved memory. Parent chat history and LangGraph checkpoints are not
inherited.

Deterministic agents invoke external capabilities through the shared
`ToolRegistry`, where profile allowlists and confirmation narrowing are enforced.
LLM and hybrid profiles use a bounded allowlisted loop for permitted reads,
capability schema discovery, own skills and authorized memory packets. Mixed
capabilities expose only declared read operations. Writes execute the unchanged
task through the existing domain handler and return its exact receipt/preview;
model text cannot supply confirmation or report unobserved success. Hybrid
profiles retain fast handlers for recognized requests and confirmations.

All inner planning/synthesis calls inherit a task-local profile execution context:
contained instructions, selected/pinned model and reasoning, scoped memory,
Hermes skills and the specialist's own thread context. They do not inherit the
main conversation checkpoint. Local profiles reject external inference; the
existing disclosure broker continues to govern profiles explicitly allowing it.

Profiles declare `memory.share_with`, `receive_from` and `share_scopes`. Agents
request relevant packets with `specialist_memory`; the main agent can request
them through `delegate_to_agent(memory_from=[...])`. Memory Orchestrator checks
both policies and retrieves attributed, bounded evidence with purpose, expiry,
user/thread identity and evidence-only authority. Calendar and Discord share
only approved shared-scope memories by default. Packet delivery is ephemeral;
it neither grants action permission nor changes durable shared knowledge.

Private agent memory remains in `agent:<AgentId>`. Agents may read validated
shared Knowledge Core context when their profile allows it. Shared writes are
proposal-only: agents cannot directly mutate canonical shared knowledge. Book
skills and all other procedural knowledge remain Hermes packages selected by the
owning agent, not invoked directly by the main model.

The main model infers which specialist owns a request from natural wording and
the compact catalog directory; users do not need to name an agent or use a
special command. It calls `delegate_to_agent` with a bounded task when the
intent is clear, including ordinary shorthand such as a live score question or
a request to find what a named person posted on X. `LiveAgentDispatcher` handles
explicit specialist selection and pending-action confirmation or cancellation.
It does not route by automatic skill matching or deterministic executor
matching. Both entry points use the same catalog, delegation runtime, and
pending-action store.

Tool authorization is intersection-based: the capability registry's existing `allowed_agents` and confirmation rules still apply, and the active profile allowlist can only narrow them.

### Specialist Response Cache

`agent/memory/specialist_cache.py` is owned by `MemoryOrchestrator`. It stores serialized `SpecialistResponse` objects keyed by profile ID, profile version, and normalized query fingerprint. Conservative lexical related-query matching is permitted only within the same profile/version.

Cache decisions are `hit`, `miss`, `stale`, or `bypass`. Freshness classes select profile TTLs:

- `live`: active scores, breaking events, and current status.
- `default`: schedules, standings, injuries, timelines, and recent uploads.
- `historical`: completed events, dated history, career facts, and transcripts.

Profile bypass terms take precedence over stored entries. Responses with errors, blocks, or pending action requests are not cacheable. If a live refresh fails and a stale response exists, the runtime returns it with `status=stale` and reduced confidence.

Specialist memory reads are limited to declared scopes. Strict profile memory packets do not include the unscoped global FTS turn history. Local Obsidian/SQLite memory retains original public names; Honcho and provider-extension synchronization receive privacy-scrubbed text.

Run audits are written to `data/memory/delegation-runs.jsonl`. They contain identifiers, profile version, executor, cache decision, timing, status, confidence, hashes, and counts only. `GET /api/agent-profiles` returns safe configuration and fallback diagnostics without instruction contents or credentials.

Profiles are application policy boundaries, not filesystem or operating-system sandboxes.

---

## 3. Privacy Layer

**Location:** `agent/privacy/`

Three files, always used in sequence:

```
classifier.py    → classify(text) → DataClass (RED/YELLOW/GREEN)
scrubber.py      → scrub(text)    → (anonymized_text, replacements)
metadata_strip.py → strip_obsidian_metadata(text, path) → clean_text
```

The privacy gate runs:
1. On every user query (before retrieval)
2. On every retrieved chunk (before injection into prompt)
3. On every tool result (before injection into prompt)
4. On every Apify result (before storage AND before LLM sees it)

The gate never runs on:
- The agent's own responses (no need — the LLM never saw raw PII)
- Files written by the agent to `Agent/` (the agent only writes what it already sanitized)

---

## 4. Memory System

### Short-Term
`data/memory/checkpoints.db` — SQLite (Docker volume), managed by LangGraph SqliteSaver.
Every turn in every thread is checkpointed. Threads resume exactly where they left off.

### Long-Term User Model (Honcho — Self-Hosted)
Honcho runs as a local Docker service backed by PostgreSQL. It is the primary
long-term memory layer, replacing the raw SQLite fact store.

**What Honcho holds:**
- Every message pair from every session (user query + agent response)
- Dialectic observations: inferred preferences, patterns, contradictions
- Confidence-weighted beliefs about the user's intellectual life
- A structured, queryable portrait that grows more accurate over time

**How it's accessed:**
- After every agent response: log the turn to Honcho
- Before every agent response: query Honcho for context relevant to the current query
- Nightly: Honcho's model is stable — no batch rebuild needed

**Docker services:** `honcho`, `honcho-deriver`, `honcho-db` (pgvector), and `honcho-cache` (Redis)
**Data location:** `honcho_data` Docker volume — your machine only
**Reasoning:** local Ollama `gemma4:12b`; embeddings use local `nomic-embed-text`
**Client:** `backend/agent/memory/honcho_client.py`

### Resolved Questions Cache
`data/memory/resolved.db` — SQLite (Docker volume).

High-confidence Q&A pairs that resolved cleanly. Used to short-circuit
retrieval on repeated similar queries without hitting the vector DB or Honcho.

```sql
CREATE TABLE resolved_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    query_hash TEXT UNIQUE,
    query TEXT,
    answer_summary TEXT,          -- 2-3 sentence summary only
    sources_json TEXT,            -- JSON list of vault paths used
    confidence REAL,
    model TEXT,
    access_count INTEGER DEFAULT 0,
    last_accessed TEXT,
    expires_at TEXT               -- 90 days from creation
);
```

### FTS5 Full-Text Search
`data/memory/fts5.db` — SQLite with FTS5 extension (Docker volume).

```sql
CREATE VIRTUAL TABLE qa_fts USING fts5(
    content,
    created,
    thread_id,
    source_paths
);
```

Rebuilt nightly from `Agent/Responses/`. Query syntax: standard SQLite FTS5.
Used for: keyword-based cross-session recall when semantic search is insufficient.

### Skills Store
`.skills/` directory — at project root, not inside Obsidian vault.

```
.skills/
├── proposed/
│   └── skill-book-summary-v1.json
├── active/
│   └── skill-retrieval-boost-v1.json
└── retired/
    └── skill-old-v0.json
```

Each skill JSON specifies: `id, name, trigger[], confidence_threshold,
instructions, citation_style, output_format, created, approved, use_count`.

---

## 5. Knowledge Layer

### Obsidian Vault
During the Personal Intelligence migration, Obsidian remains the active source
for existing raw imports and the maintained Knowledge Wiki. The target source of
truth is the local Knowledge Core; Obsidian becomes an optional readable
projection and explicit user-authored source surface after verified cutover.
Location: `OBSIDIAN_VAULT_PATH` (from `.env`).
The vault is plain Markdown. It requires no Docker, no database, no special tooling.
If every Docker service stopped tomorrow, the vault remains intact and
human-readable. The embedded Knowledge Core also runs without Docker.

Every file the agent uses was originally a human choice — a book you imported,
a note you wrote, a post you saved. The vault is yours. The agent reads from it.

### Vector Index (Qdrant — Invisible Infrastructure)
**Purpose:** Semantic similarity search across vault chunks.
**Location:** Local Docker container, `localhost:6333`.
**Collections:**
- `obsidian_vault` — all indexed vault content (chunks with folder metadata)
- `agent_queries` — all past user queries (for dedup and pattern detection)

Qdrant is invisible in normal use. You never interact with it directly.
The only surface: `/reindex` in chat/API surfaces, which rebuilds it from scratch.
It is a cache, not a source of truth. Delete it any time — `/reindex` restores it.

**Docker service:** `qdrant`
**Data location:** `qdrant_data` Docker volume — your machine only
**Port:** `6333` (internal use only — not exposed to external network)

### Embedding Model (BGE-M3)
**Location:** Downloaded from HuggingFace on first run, cached locally.
**Runs:** Fully offline — no API call, no network request.
**Dimension:** 1024
**Use:** Embedding queries, vault chunks, skill triggers, and Q&A pairs.

### Reranker (cross-encoder/ms-marco-MiniLM-L-6-v2)
**Location:** Downloaded from HuggingFace on first run, cached locally.
**Runs:** Fully offline.
**Use:** Rerank retrieved chunks by true relevance before injecting into prompt.
**Size:** ~80MB — fast and lightweight.

### Graph Retriever
**Location:** `agent/rag/graph_retriever.py`
**Purpose:** Walk Obsidian wikilinks to find connected notes before/alongside vector search.

Three-stage retrieval for every query:
1. **Graph walk** — follow wikilinks from detected note mentions
2. **Vector search** — semantic similarity across all indexed chunks
3. **Merge and rerank** — combine results, boost chunks connected by wikilinks to other top-scoring chunks

---

## 6. Workflow for New Knowledge

When new content enters the vault, this is the sequence:

```
1. SELECTION
   User adds a Twitter archive (via import_twitter_via_apify.py)
   or a note manually. Book ingestion is owned by Knowledge Core and
   BooksAgent under docs/adr/0001 through 0007.

2. CLEANING
   Importers strip metadata, scrub PII for private folders,
   strip Obsidian frontmatter noise, preserve structure.

3. WRITE TO VAULT
   Clean Markdown files land in the correct folder.
   Wikilinks are written to connect chapters to book cards,
   book cards to _index.md.

4. INDEXING
   User runs /reindex in the chat, or the watcher detects
   the new file (agent/obsidian/watcher.py uses watchdog).
   VaultIngester embeds each chunk with BGE-M3, stores in Qdrant.
   FTS5 index is updated nightly (or on manual /reindex).

5. SYNTHESIS (optional, on next agent interaction)
   If the user asks about the new content, the agent retrieves
   relevant chunks, synthesizes an answer, and writes a summary
   back to Agent/Memories/ if the answer represents a significant
   new synthesis not previously in the vault.

6. SKILL SIGNAL (if applicable)
   If the user asks the same kind of question about new content
   repeatedly, the nightly job detects the pattern and drafts a
   skill proposal. User approves. Skill activates.
```

---

## 7. Security & Ownership

### Data Residency
- Vault: your machine only.
- Qdrant: your Docker container, your machine.
- SQLite databases: your machine, `data/memory/`.
- `.skills/`: your machine, project root.
- Audit log: your machine, `data/memory/audit_log.jsonl`.

Nothing leaves your machine except:
- Scrubbed, tagged, PII-stripped queries → OpenRouter → provider
- Apify scraping calls (your Apify token, results return to your machine)
- DuckDuckGo web searches (no account, no tracking)

Honcho runs locally. Its PostgreSQL database is a Docker volume on your machine,
and its configured derivation, dialectic, and embedding routes point to local
Ollama. No Honcho data is sent to Plastic Labs' servers in this configuration.

### OpenRouter
- `data_collection: deny` on every request.
- ZDR-compatible providers only (Fireworks, Together, DeepInfra).
- No prompt logging enabled in OpenRouter account settings.
- No "use inputs/outputs" opt-in.

### The Vault Is Yours
No third party has a copy of your Obsidian vault.
No third party has access to your long-term memory databases.
No third party can read your audit log.

If you stop using Vellum tomorrow, you have:
- A vault full of well-organized Markdown files you can read with any editor.
- SQLite databases you can query with any SQLite tool.
- An audit log you can read with any text editor.

There is no proprietary format. There is no vendor lock-in. Everything is yours.

---

## 8. Data Flow Diagram

```
User types a query
        │
        ▼
Privacy Gate
  │  Classify (RED → block)
  │  Scrub PII (YELLOW → anonymize)
  │  Tag (<PROTECTED> / <QUERY>)
  │
  ▼
Resolved questions cache check
  │  Similar query answered before with high confidence? → return cached summary
  │  Otherwise continue
  │
  ▼
Query retained in canonical conversation storage; derived retrieval indexes update through the Memory Orchestrator
  │
  ▼
Parallel context gathering
  │
  ├── Honcho query (user model context relevant to this query)
  │     → "User tends to frame resilience through Stoic lens,
  │        not Buddhist. Last 3 asks on this topic: [...]"
  │
  └── Retrieval (three-stage)
        Stage 1: Graph walk (wikilinks from detected note mentions)
        Stage 2: Vector search (Qdrant — invisible, automatic)
        Stage 3: Merge + rerank (cross-encoder, wikilink boost)
        Fallback: FTS5 (if vector confidence < threshold)
  │
  ▼
Folder policy check (strip chunks from private folders)
  │
  ▼
Main skill activation
  │  Match packages to the current request
  │  Exclude specialist-owned skills from main-agent context
  │
  ▼
Prompt construction
  │  System prompt
  │  + active skill instructions
  │  + Honcho user context
  │  + sanitized retrieved vault chunks
  │  + conversation history (SqliteSaver)
  │
  ▼
Select runtime model and provider; disable the tool loop when unsupported
  │
  ├── Main model may call delegate_to_agent for a catalog specialist
  │     Specialist receives the bounded task and allowed context
  │
  ▼
Local Ollama inference or configured cloud provider route
  │
  ▼
Response received (streaming tokens to UI)
  │
  ▼
Store response
  │  Write Q&A pair to Agent/Responses/
  │  Write wikilinks back to source notes
  │  Index Q&A in FTS5
  │  Store in resolved cache if confidence > 0.85 and not regenerated
  │
  ▼
Honcho update
  │  Log user message to Honcho session
  │  Log agent response to Honcho session
  │  Honcho's dialectic engine updates user model automatically
  │
  ▼
Skill signal detection
  │  Check if this turn contributes to a recurring pattern
  │  If yes, increment signal count in resolved.db
  │
  ▼
Audit log
  │  Write metadata only (no content) to audit_log.jsonl
  │
  ▼
Response displayed to user
```

---

## 9. File Reference

| Path | Purpose |
|---|---|
| `backend/agent/graph/agent.py` | Main StateGraph, provider-neutral prompt, and tool discovery |
| `backend/agent/tools/delegation.py` | Typed main-agent specialist delegation entry point |
| `agent/tools/vault_search.py` | Main RAG tool with privacy + folder policy |
| `agent/tools/web.py` | DuckDuckGo search tool |
| `agent/tools/apify.py` | Amazon scraper tool |
| `agent/tools/filesystem.py` | File read/list tools |
| `agent/tools/obsidian_write.py` | Note creation, Q&A storage |
| `agent/privacy/classifier.py` | RED/YELLOW/GREEN classification |
| `agent/privacy/scrubber.py` | Presidio PII anonymization |
| `agent/privacy/metadata_strip.py` | Obsidian frontmatter stripping |
| `agent/obsidian/vault.py` | Read/write Obsidian notes |
| `agent/obsidian/ingester.py` | Bulk vault ingestion into Qdrant |
| `agent/obsidian/folder_policy.py` | Folder access permissions |
| `agent/obsidian/watcher.py` | watchdog for vault changes |
| `agent/rag/embedder.py` | BGE-M3 local embedding |
| `agent/rag/store.py` | Qdrant client wrapper |
| `agent/rag/reranker.py` | Cross-encoder reranking |
| `agent/rag/graph_retriever.py` | Wikilink-aware retrieval |
| `agent/llm/openrouter.py` | OpenRouter client, ZDR enforced |
| `agent/tools/filesystem.py` | PowerShell CLI file tools (vault-confined, no MCP) |
| `agent/mcp/apify_tools.py` | Apify MCP wrapper |
| `agent/memory/honcho_client.py` | Honcho self-hosted user model client |
| `agent/memory/fts5.py` | FTS5 full-text search index |
| `agent/memory/resolved.py` | Resolved questions cache |
| `agent/memory/skills.py` | Skill loader and manager |
| `agent/usage/audit_log.py` | Usage logging |
| `agent/usage/suggestions.py` | Pattern analysis and suggestions |
| `agent/usage/pricing.py` | OpenRouter pricing cache |
| `agent/scheduler/digest.py` | Nightly digest job |
| `agent/scheduler/reflection.py` | Weekly/monthly reflection jobs |
| `agent/scheduler/skill_detector.py` | Skill signal detection job |
| `agent/cli.py` | Fallback CLI |
| `scripts/import_twitter_archive.py` | Twitter archive importer |
| `scripts/import_twitter_via_apify.py` | Twitter Apify importer |
| `scripts/ledger.py` | Standalone ledger CLI |
| `data/memory/checkpoints.db` | LangGraph thread checkpoints |
| `data/memory/fts5.db` | Full-text search index |
| `data/memory/resolved.db` | Resolved questions cache |
| `data/memory/audit_log.jsonl` | Usage audit log |
| `.skills/proposed/` | Agent-proposed skills awaiting approval |
| `.skills/active/` | Approved, active skills |
| `.env` | Configuration (never committed) |
| `SOUL.md` | Identity and learning philosophy |
| `docker-compose.yml` | Honcho API, deriver, pgvector, and Redis services |
| `CLAUDE.md` | Technical operations manual |
| `AGENT_ARCHITECTURE.md` | This file |
| `BRAND.md` | Brand identity |
| `DESIGN.md` | Visual and interaction principles |
| `PROMPTS.md` | Prompt library for Claude Code |
