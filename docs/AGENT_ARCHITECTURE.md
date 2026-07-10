# AGENT_ARCHITECTURE.md
> System configuration and stack for Vellum.
> Read this alongside SOUL.md, CLAUDE.md, and BRAND.md.
> This is the source of truth for how all parts of the system connect.

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
│   LangGraph create_react_agent                                      │
│   System prompt (SOUL.md values + operational rules)                │
│   SqliteSaver checkpointer (thread persistence)                     │
│   Skill loader (.skills/active/ → injects into system prompt)       │
│   Tool registry (search_my_notes, web_search, filesystem, apify,   │
│                  create_note, append_to_note, search_amazon)        │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
┌────────▼────────┐   ┌──────────▼──────────┐  ┌────────▼────────┐
│  PRIVACY LAYER  │   │    MEMORY SYSTEM     │  │  INFERENCE      │
│                 │   │                      │  │                 │
│ Classifier      │   │ Short-term:          │  │ OpenRouter API  │
│ Presidio scrub  │   │   SqliteSaver        │  │ ZDR enforced    │
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
│   ├── Books/        (private — indexed only)                        │
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

  qdrant      → localhost:6333   (vector index — invisible in use)
  honcho      → localhost:8001   (user modeling — queried per turn)
  honcho-db   → internal only    (PostgreSQL backing Honcho)
  sqlite      → data/memory/     (checkpoints, FTS5, resolved cache)

  All Docker volumes are local. No data leaves your machine.
  /reindex rebuilds Qdrant from scratch if ever needed.
  Honcho data persists in honcho_data Docker volume.

─────────────────────── DEVELOPER TOOLING ───────────────────────────

  Graphify    → /graphify . in Claude Code (build sessions only)
                Maps codebase into queryable knowledge graph.
                No runtime role. Not used by the agent.

```

---

## 1. Interfaces

### Default Vellum Streaming Contract

The active frontend surface is `design/Velllum/uploads/vellum-workspace.html`.
The retired `frontend/ui/vellum-chat.html` is not a target for new stream work.

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
LangGraph `create_react_agent` — not a custom graph, not a multi-node pipeline.
The LLM decides which tools to call, in what order, how many times.

```python
agent = create_react_agent(
    model=openrouter_llm,
    tools=[
        search_my_notes,   # RAG + privacy + folder policy
        web_search,        # DuckDuckGo, privacy-gated
        search_amazon,     # Apify, always private
        read_file,         # Filesystem MCP, vault-restricted
        list_files,        # Filesystem MCP, vault-restricted
        browser_action,    # Playwright MCP, isolated browser control
        github_read,       # GitHub MCP, repository context
        github_write,      # GitHub MCP, gated repository mutation
        git_action,        # Local git status/log/pull/commit/push
        obsidian_api,      # Obsidian Local REST API MCP
        create_note,       # Write to Agent/ only
        append_to_note,    # Write to Agent/ only
    ],
    checkpointer=SqliteSaver.from_conn_string("data/memory/checkpoints.db"),
    state_modifier=VELLUM_SYSTEM_PROMPT,
)
```

### System Prompt Location
`agent/graph/agent.py` — the `VELLUM_SYSTEM_PROMPT` constant.
The prompt encodes: identity (from SOUL.md), voice rules (from BRAND.md),
operational constraints (from CLAUDE.md), and the three values (truth, curiosity, care).

The system prompt is versioned in git. It is never modified by the agent.
Changes to the system prompt are made by the user, deliberately, in the file.

### Skill Loading
Before each agent invocation, the skill loader checks `.skills/active/`:

```python
def load_relevant_skills(query: str) -> str:
    """
    Returns a skill block to prepend to the system prompt,
    or empty string if no skills match.
    """
    query_embedding = embedder.embed(query)
    active_skills = load_active_skills()
    matches = []
    for skill in active_skills:
        trigger_embedding = embedder.embed(" ".join(skill["trigger"]))
        similarity = cosine_similarity(query_embedding, trigger_embedding)
        if similarity > skill["confidence_threshold"]:
            matches.append(skill)
    if not matches:
        return ""
    skill_block = "\n\n## Active Skills\n"
    for skill in matches:
        skill_block += f"\n### {skill['name']}\n{skill['instructions']}\n"
    return skill_block
```

Skills are loaded into the system prompt for the current turn only.
They do not persist across turns unless triggered again.

### Profile-Based Specialist Delegation

Runtime specialist configuration is split into persistent profiles and ephemeral runs.

`agent/profiles/` owns the strict profile schema, safe built-in defaults, YAML loading, diagnostics, instruction-path containment, and context-local tool policy. Profile YAML is loaded from `data/agent_profiles/`. Existing deterministic agents remain registered through `PupilRegistry`; a newly discovered `executor: llm` profile can be selected directly by an active routing skill without a Python pupil class.

`agent/master/runtime.py` creates a fresh `DelegationRunResult` for every specialist task. Deterministic profiles receive only the current goal through their existing `answer(query)` contract. LLM profiles receive a new two-message invocation containing their profile system instructions and a human task packet with the goal, explicit context, and profile-approved memory. Parent chat history and LangGraph checkpoints are not inherited.

Routing order is:

1. Pending confirmed action, which never enters cache.
2. Active routing skill targeting a registered pupil or profile-only LLM agent.
3. Deterministic `PupilRegistry.match()` fallback.
4. Return control to Vellum.

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

**Docker service:** `honcho` + `honcho-db` (PostgreSQL)
**Data location:** `honcho_data` Docker volume — your machine only
**Client:** `agent/memory/honcho_client.py`

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
The single source of truth. All agent knowledge is derived from Markdown files here.
Location: `OBSIDIAN_VAULT_PATH` (from `.env`).
The vault is plain Markdown. It requires no Docker, no database, no special tooling.
If every Docker service stopped tomorrow, your vault is intact and human-readable.

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
   User adds a book (via import_book.py), a Twitter archive
   (via import_twitter_via_apify.py), or any note manually.

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

Honcho runs locally. Its PostgreSQL database is a Docker volume on your machine.
No Honcho data is sent to Plastic Labs' servers in the self-hosted configuration.

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
Query stored to Agent/Queries/ + agent_queries Qdrant collection
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
Skill loader
  │  Check .skills/active/ for matching skills
  │  Inject matching skill instructions into system prompt
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
Model routing (primary / fast / fallback based on retrieval confidence)
  │
  ▼
OpenRouter API call (ZDR enforced, data_collection: deny)
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
| `agent/graph/agent.py` | Core agent: create_react_agent, system prompt, tool list |
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
| `agent/mcp/filesystem_tools.py` | Filesystem MCP wrapper |
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
| `scripts/import_book.py` | EPUB book importer |
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
| `docker-compose.yml` | Qdrant + Honcho + PostgreSQL services |
| `CLAUDE.md` | Technical operations manual |
| `AGENT_ARCHITECTURE.md` | This file |
| `BRAND.md` | Brand identity |
| `DESIGN.md` | Visual and interaction principles |
| `PROMPTS.md` | Prompt library for Claude Code |
