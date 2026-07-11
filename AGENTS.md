# AGENTS.md
> Technical operations manual for Vellum.
> Read this alongside SOUL.md, BRAND.md, and AGENT_ARCHITECTURE.md.
> This file defines *how* the agent operates technically, not what it is philosophically.
> Paste this into Codex or Codex as the operational contract for every build session.

---

## 1. Privacy & Scrubbing Protocol (CRITICAL — READ FIRST)

Privacy is architecture, not policy. Every piece of data that touches the pipeline goes through
the privacy gate before it touches any external API. No exceptions.

### The Privacy Gate

Every outgoing query passes through four stages in order:

```
RAW INPUT
    ↓
Stage 1: Classification (RED / YELLOW / GREEN)
    ↓
Stage 2: PII Scrubbing (Presidio — runs locally, no network)
    ↓
Stage 3: Tagging (<PROTECTED> / <QUERY>)
    ↓
Stage 4: Folder Policy Check (can this content go to LLM?)
    ↓
SANITIZED OUTPUT → OpenRouter
```

**Stage 1 — Classification**

Every query is classified before anything else:

- `RED` — contains sensitive patterns (passwords, SSNs, financial credentials, health data).
  BLOCK immediately. Do not proceed. Return a refusal in one sentence.
- `YELLOW` — contains personal context (names, locations, dates, opinions).
  SCRUB with Presidio, then proceed with `<PROTECTED>` tags on replaced values.
- `GREEN` — general knowledge queries, no personal context.
  Proceed with `<QUERY>` tag. No scrubbing needed.

Classification is performed locally using `agent/privacy/classifier.py`.
Classification NEVER makes a network call.

**Stage 2 — PII Scrubbing**

For YELLOW queries, run Presidio anonymizer (local, offline) before building the prompt.
Replacements:
- Names → `[PERSON]`
- Emails → `[EMAIL]`
- Phone numbers → `[PHONE]`
- Locations → `[LOCATION]`
- Dates → `[DATE]` (optional, context-dependent)
- Credit cards, SSNs → `[REDACTED]`

Store the mapping of original → replacement locally in the session.
If the response contains placeholders, de-anonymize before displaying to user.

**Stage 3 — Tagging**

After scrubbing, tag the query for the LLM:

```
<PROTECTED>
[Scrubbed personal context here — names replaced, dates replaced]
</PROTECTED>

<QUERY>
[The actual question or task, safe to process]
</QUERY>
```

The LLM sees the tags and understands the privacy boundary.
Raw personal data never appears in the LLM's input.

**Stage 4 — Folder Policy Check**

Before including any Obsidian chunk in the LLM prompt, check its folder against
`agent/obsidian/folder_policy.py`.

Folders and their permissions:
- `X/` — INDEXED locally, SENT to LLM, TOOL ACCESSIBLE
- `Youtube/` — INDEXED locally, SENT to LLM, TOOL ACCESSIBLE
- `Books/` — INDEXED locally, NEVER sent to LLM raw
- `feedback/` — INDEXED locally, NEVER sent to LLM raw
- `Sports/` — INDEXED locally, SENT to LLM
- `Agent/` — INDEXED locally, SENT to LLM

Private folder chunks (Books, feedback, and any default private folders) contribute
to retrieval scoring but their content is NEVER injected into the LLM prompt.
Public folders like X, Youtube, Sports, and Agent can be used as LLM context.

### What the External API Never Sees

The following must never appear in any payload sent to OpenRouter:
- Real names of people (replaced with [PERSON])
- Email addresses
- Physical addresses or precise locations
- Financial account numbers or passwords
- Raw content from private folders (Books, feedback, and default private folders)
- File paths from the user's machine
- The user's real handle or username from any platform

---

## 2. Memory & Retrieval

Vellum uses a three-tier memory system. Each tier serves a different purpose
and operates at a different time scale.

### Tier 1 — Short-Term (Active Session)

- LangGraph's `SqliteSaver` checkpointer maintains the active conversation thread.
- Stored at `data/memory/checkpoints.db`.
- Each thread has a unique `thread_id`; all turns in a thread are checkpointed.
- Short-term memory is never summarized or compressed during an active session.
- Maximum active context: the current thread. Prior threads are not in context
  unless explicitly retrieved.

### Tier 2 — Long-Term (Cross-Session Recall)

Three mechanisms, all local:

**Honcho user model (self-hosted, PostgreSQL in Docker)**
- The primary long-term memory layer. Replaces the raw SQLite fact store.
- Honcho runs as a local server (`http://localhost:8000` by default).
- Every message pair (user query + agent response) is sent to Honcho after each turn.
- Honcho maintains a structured, queryable portrait of the user across all sessions.
- At the start of each agent turn, query Honcho for context relevant to the current query.
- Honcho's PostgreSQL data lives in a Docker volume on your machine. Never leaves.
- Self-hosted repo: `https://github.com/plastic-labs/honcho`

```python
# Send each turn to Honcho after response is generated
honcho_client.apps.users.sessions.messages.create(
    app_id=HONCHO_APP_ID,
    user_id="default",
    session_id=thread_id,
    content=query,
    role="user"
)
honcho_client.apps.users.sessions.messages.create(
    app_id=HONCHO_APP_ID,
    user_id="default",
    session_id=thread_id,
    content=response,
    role="assistant"
)

# At retrieval time — get user context relevant to current query
context = honcho_client.apps.users.sessions.chat(
    app_id=HONCHO_APP_ID,
    user_id="default",
    session_id=thread_id,
    query=current_query
)
```

**FTS5 full-text search index** (`data/memory/fts5.db` — SQLite in Docker)
- Canonical conversations are indexed from `data/ui/conversations.json`; Obsidian conversation notes are projections.
- Enables keyword-based retrieval across all past sessions.
- Query: `SELECT content FROM qa_fts WHERE qa_fts MATCH ?`
- Used when semantic vector search returns low confidence and the query
  contains specific keywords that might exist verbatim in past sessions.
- FTS5 is a derived index managed by the Memory Orchestrator. See `docs/memory-knowledge-architecture.md`.

**Resolved questions cache** (`data/memory/resolved.db` — SQLite in Docker)
- High-confidence Q&A pairs that resolved cleanly (confidence > 0.85, user did not regenerate).
- On future similar queries, the cache is checked first before full retrieval.
- Schema: `id, timestamp, query_hash, query, answer_summary, sources_json, confidence, model`
- Cache entries expire after 90 days unless accessed again.

**When to use which:**
- For "what are my preferences / beliefs / patterns" → Honcho first.
- For "what did I say about X" queries → FTS5 first (keyword match), then vector.
- For "find notes related to this idea" → vector search first (semantic similarity).
- For repeated near-identical queries → resolved questions cache first.
- For highly specific named queries ("what did I write about Tarkovsky in March") → FTS5.

**Summarization before injection:**
When retrieving past session context via FTS5, do NOT inject raw past Q&A pairs
into the current prompt. Use the fast model (Gemma 4 12B) to summarize the
retrieved turns into 2-3 sentences, then inject the summary. This keeps token
usage bounded regardless of session history length.

### Tier 3 — Procedural (Skills)

- `.skills/proposed/` — skills drafted by the agent, awaiting user approval
- `.skills/active/` — approved skills, loaded on demand
- `.skills/retired/` — deactivated skills (kept for audit, not loaded)

Each skill is a JSON file with this structure:
```json
{
  "id": "skill-book-summary-v1",
  "name": "Book summary in my voice",
  "trigger": ["summarize", "book", "what does X say about"],
  "confidence_threshold": 0.75,
  "instructions": "When summarizing a book for this user...",
  "citation_style": "italic Roman numeral footnotes",
  "output_format": "prose, max 400 words, 3 footnotes minimum",
  "created": "2026-01-12",
  "approved": "2026-01-13",
  "use_count": 14,
  "last_used": "2026-05-01"
}
```

Skills are loaded by the agent when the query's embedding has cosine similarity
> `confidence_threshold` with the skill's trigger terms. Multiple skills can
load for a single query. Skills modify the system prompt for that turn only;
they do not persist beyond the current response.

---

## 3. MCP Integration

MCP (Model Context Protocol) is used for tool connections. The agent connects
to MCP servers for specific capabilities; it does NOT use MCP to ingest the
entire Obsidian vault into context.

### Active MCP Servers

**Filesystem MCP** (`@modelcontextprotocol/server-filesystem`)
- Scope: restricted to `OBSIDIAN_VAULT_PATH` only
- Used for: reading specific note files when the agent needs the full text
  of a note it has already identified via vector retrieval
- Never used for: bulk reading, directory traversal, writing outside `Agent/`

**Apify (REST API for scheduled ingestion + MCP for agent calls)**
- REST API used by scheduled YouTube ingestion with `APIFY_API_TOKEN`.
- MCP (`https://mcp.apify.com/sse`) used for agent-driven scraping (Amazon product lookups).
- Output is ALWAYS stored locally first, THEN scrubbed if YELLOW, THEN
  summarized before the LLM sees any of it.
- Never used as a general web scraper without explicit user instruction.

**xAI OAuth X Search**
- Scheduled X ingestion uses the xAI Responses API with the `x_search` tool.
- Requires `XAI_OAUTH_ACCESS_TOKEN` or `data/xai-oauth.json`; no Hermes CLI
  or `APIFY_API_TOKEN` is required for `Vault/Library/X/`.
- Only cited X status URLs with clear extracted text may be written into
  `Library/X/<handle>/`.

**Playwright MCP** (`@playwright/mcp@latest --isolated`)
- Used for: browser navigation and accessibility snapshots through `browser_action`
- Default mode: navigation/snapshot/read-only browser inspection
- Mutating actions (`click`, `type`, `press_key`, `select_option`, `hover`) require
  `PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true`
- Never used for: banking, purchases, password managers, account settings,
  destructive operations, or sending messages without an explicit control layer

**GitHub MCP** (`https://api.githubcopilot.com/mcp/`)
- Used for: GitHub repository, code, issue, PR, commit, branch, tag,
  release lookup through `github_read`, plus controlled repo/file mutation
  through `github_write`
- Requires `GITHUB_MCP_TOKEN` or `GITHUB_PAT`
- Writes require `GITHUB_MCP_ALLOW_WRITES=true`
- Destructive writes (`delete_repository`, `delete_file`) additionally require
  `GITHUB_MCP_ALLOW_DESTRUCTIVE=true`
- Local `pull`, `commit`, and `push` use `git_action` and require
  `GIT_TOOL_ALLOW_WRITES=true`
- Never used for: history rewrite, delete-style refs, or unrequested destructive
  repository actions

**Obsidian API/MCP** (`OBSIDIAN_MCP_URL`, default `https://127.0.0.1:27124/mcp/`)
- Used for: Obsidian Local REST API access through `obsidian_api`
- Requires `OBSIDIAN_API_KEY`
- Read actions include vault list/read/search, document map, tags, active file,
  periodic note path, and command listing
- Writes require `OBSIDIAN_MCP_ALLOW_WRITES=true`
- Deletes require `OBSIDIAN_MCP_ALLOW_DESTRUCTIVE=true`
- Command execution requires `OBSIDIAN_MCP_ALLOW_COMMANDS=true`
- Default SSL verification is off because the local plugin commonly uses a
  self-signed certificate; enable `OBSIDIAN_MCP_VERIFY_SSL=true` after trusting it
- Default transport is REST because the Local REST API plugin exposes REST on
  `27123/27124`; set `OBSIDIAN_MCP_USE_STREAM=true` only when using a separate
  streamable MCP bridge at `OBSIDIAN_MCP_URL`

**Context7 MCP** (`CONTEXT7_MCP_URL`, default `https://mcp.context7.com/mcp`)
- Used for: up-to-date software library documentation lookup through `library_docs`
- Two-step workflow: `resolve-library-id` (name → Context7 ID) then
  `get-library-docs` (ID + optional topic/tokens → focused docs)
- Read-only — Context7 exposes no mutating tools
- `CONTEXT7_API_KEY` is optional; when set it is sent as a bearer token for
  higher rate limits, otherwise calls run anonymously
- Never used for: anything other than library/framework documentation lookup;
  output is public OSS docs and is not scrubbed

**GitMCP** (`GITMCP_MCP_URL`, default `https://gitmcp.io/docs`)
- Hosted, free, read-only — `idosal/git-mcp` turns any public GitHub repo's
  documentation and code into MCP tools, accessed through `repo_docs`
- Actions exposed: `match` (library name → owner/repo), `fetch_docs`,
  `search_docs`, `search_code`, and `fetch_url` (single reference URL)
- No authentication required
- Use cases: arbitrary repo documentation and in-repo code search. Prefer
  `library_docs` (Context7) for well-known libraries and `github_read` for
  structured PR/issue/commit data
- Never used for: anything beyond public-repo documentation/code lookup;
  output is public OSS material and is not scrubbed

**Context Mode** (`mksglu/context-mode`, stdio via `CONTEXT_MODE_MCP_COMMAND` /
`CONTEXT_MODE_MCP_ARGS`, default `npx -y context-mode`)
- Used for: sandboxed code execution and indexed retrieval through `context_mode`
- Surfaced actions (subset of upstream's 11 tools):
  - `execute` — run a script in one of 12 languages; only stdout enters context
  - `index` — chunk markdown into a local FTS5/BM25 store
  - `search` — BM25-ranked retrieval over previously indexed content
  - `fetch_and_index` — fetch a URL, convert to markdown, index; 24h cache,
    HTTP(S) only (cloud metadata + link-local IPs blocked by upstream)
  - `stats`, `doctor` — operational diagnostics
  - `purge` — wipe the local index; requires `confirm=true`
- Requires Node.js ≥22.5 on PATH so `npx -y context-mode` resolves
- Hook-based auto-routing (the upstream's headline feature) is NOT used —
  Vellum's LangGraph loop has no hook framework, so `context_mode` is invoked
  explicitly by the agent like any other tool
- `ctx_fetch_and_index` output does NOT pass through Vellum's privacy gate;
  summarize before quoting and never mix raw fetch_and_index content with
  private-folder context in the same response
- Never used for: bypassing the vault-first rule, indexing private-folder
  content into Context Mode's separate FTS5 store, or running `purge`
  without explicit user confirmation

### MCP Usage Rules

1. MCP tool calls are logged in the audit log with tool name, call count, and latency.
2. MCP results are NEVER injected raw into the LLM prompt.
3. Filesystem MCP reads are limited to files already identified by vector retrieval.
   The agent does not use MCP to browse or discover; it uses MCP to fetch.
4. All MCP errors are handled gracefully. Failure message: one word. "Unreachable."


---

## 3b. Honcho Integration (Self-Hosted User Modeling)

Honcho is the user modeling layer. It is NOT a cloud service in this deployment.
It runs as a local FastAPI server, backed by PostgreSQL in Docker.

### Setup

Honcho is added to `docker-compose.yml` alongside Qdrant:

```yaml
honcho:
  image: plasticlabs/honcho:latest
  ports:
    - "8001:8000"
  environment:
    - DATABASE_URL=postgresql://honcho:honcho@honcho-db:5432/honcho
  depends_on:
    - honcho-db

honcho-db:
  image: postgres:16
  environment:
    POSTGRES_USER: honcho
    POSTGRES_PASSWORD: honcho
    POSTGRES_DB: honcho
  volumes:
    - honcho_data:/var/lib/postgresql/data

volumes:
  honcho_data:
  qdrant_data:
```

### Environment Variables

Add to `.env`:
```env
HONCHO_BASE_URL=http://localhost:8001
HONCHO_APP_ID=vellum
HONCHO_USER_ID=default
```

### Client Location

`agent/memory/honcho_client.py` — a thin wrapper around the Honcho Python SDK.

```python
from honcho import Honcho

honcho = Honcho(base_url=settings.HONCHO_BASE_URL)

# Ensure app exists
app = honcho.apps.get_or_create(name=settings.HONCHO_APP_ID)

# Ensure user exists
user = honcho.apps.users.get_or_create(
    app_id=app.id,
    name=settings.HONCHO_USER_ID
)
```

### What Honcho Stores

Honcho stores messages, sessions, and metamessages. In Vellum's use:

- **Sessions** map 1:1 to LangGraph thread IDs
- **Messages** are every user query and agent response, in order
- **Metamessages** are Honcho's internal dialectic observations about the user
  (these are generated by Honcho automatically — you don't write them)

### How the Agent Uses Honcho

**After every response (in `store_response` tool):**
```python
# Log the turn to Honcho
session = honcho_client.get_or_create_session(thread_id)
honcho_client.add_message(session.id, content=query, role="user")
honcho_client.add_message(session.id, content=response, role="assistant")
```

**Before composing each prompt (in `agent/graph/agent.py`):**
```python
# Get Honcho's current understanding of the user, relevant to this query
honcho_context = honcho_client.chat(
    session_id=thread_id,
    query=clean_query
)
# Inject into system prompt as "User context from memory:"
```

### Privacy of Honcho Data

- PostgreSQL data volume is on your machine only
- Honcho server listens on localhost only (no external port binding)
- Honcho never calls external APIs (self-hosted version is fully local)
- If you stop the Docker container, your Honcho data persists in the Docker volume
- To export: `docker exec honcho-db pg_dump honcho > honcho_backup.sql`

### Graphify (Developer Tool — Not Runtime)

**Graphify** (`github.com/safishamsi/graphify`) is installed as a slash command
skill for Codex and Codex. It maps the Vellum codebase into a queryable
knowledge graph, making build sessions coherent across long conversations.

Install once:
```bash
pip install graphifyy
graphify install   # registers /graphify for Codex
```

Use at the start of every build session in Codex:
```
/graphify .
```

Graphify operates only during development. It has no role in Vellum's runtime.
It does not touch the vault, does not call OpenRouter, does not affect retrieval.
It is a developer productivity tool, used during construction, invisible in production.

---

## 4. Automation & Routines

All scheduled tasks run locally via APScheduler. They do not require an
internet connection (except where noted), do not make unauthorized vault changes,
and do not send data to external services.

### Nightly Digest (2:00 AM daily)
- Read recent canonical conversations and pending memories through the Memory Orchestrator
- Extract skill signals using fast model (Gemma 4 12B via OpenRouter)
- Write synthesis note to `Agent/Digests/YYYY-MM-DD.md`
- Maintain summaries, saved memories, archive state, and the derived FTS5 index
- Honcho automatically updates its user model on every turn — no batch job needed
- Send `data_collection: deny` on all OpenRouter calls in this job

### Weekly Reflection (2:00 AM Sunday)
- Read all digests from the past 7 days
- Synthesize into a reflection note using fast model
- Write to `Agent/Reflections/Weekly/YYYY-MM-DD.md`
- Note structure: themes, most-cited books, patterns observed

### Monthly Provocation (2:00 AM, 1st of month)
- Read weekly reflections from the past month
- Identify one apparent tension or gap in the user's thinking
- Write a single question (not an answer) to `Agent/Reflections/Monthly/YYYY-MM.md`
- This question should make the user think, not inform them

### Skill Signal Detection (runs after nightly digest)
- Query resolved questions cache for repeated query patterns (cosine similarity > 0.82)
- Query Honcho for recurring preference signals the agent has observed
- Group signals by semantic similarity
- If any group has 3+ signals with consistent pattern, draft a skill proposal
- Write proposed skill JSON to `.skills/proposed/`
- Write a human-readable note to `Agent/Skills/Proposed/` explaining the proposal
- DO NOT activate the skill. Wait for user approval.

### FTS5 Index Rebuild (runs after nightly digest)
- Read canonical conversations through the Memory Orchestrator
- Rebuild `data/memory/fts5.db` as a disposable derived index
- Log: number of documents indexed, index size, rebuild duration

### Sports Research (on demand)
- SportsAgent runs only when the user asks a sports-related question.
- It uses live providers and does not run a sports daemon or curiosity loop.
- `Library/Sports/` is legacy reference material, not a canonical truth source.

---

## 5. Vault Write-Back Standards

When the agent writes to the Obsidian vault, it follows these rules strictly.

### Allowed Write Locations

```
Meta/                           ← READ-ONLY for agent; user-authored
Projects/<slug>/vellum.md       ← READ-ONLY; user-authored
Projects/<slug>/hot.md          ← Vellum may REWRITE (gated by active_project)
Projects/<slug>/log.md          ← Vellum may APPEND (gated by active_project)
Projects/<slug>/notes/          ← Vellum may WRITE (per project's Allowed Actions)
Agent/Conversations/    ← readable projection of canonical chat history
Agent/Memories/         ← synthesized higher-order observations
Agent/Connections/      ← cross-note connections discovered by agent
Agent/Reflections/      ← weekly, monthly synthesis notes
Agent/Digests/          ← nightly digest notes
Agent/Skills/Proposed/  ← human-readable skill proposals
Agent/Skills/Active/    ← active skill notes (mirrors .skills/active/)
Agent/Saved/            ← user-saved responses (via Ctrl+S)
```

### Forbidden Write Locations

The agent NEVER writes to or modifies:
- `Meta/` — user-authored identity layer (profile, goals, principles)
- `Projects/<slug>/vellum.md` — user-authored project charter
- `Library/` — reference material (X, Youtube, Books, Sports, Codex, Codex, feedback)
- Any project's files when that project is not the active project on the current thread (enforced by ProjectContext)
- Any folder not listed under Allowed above

### ProjectContext gating

`agent/memory/project_context.py` enforces a stricter dynamic rule on top of folder_policy:
- `hot.md` / `log.md` / `notes/` writes are only permitted to the **active project** for the
  current thread (`sessions.thread_state.active_project`). Writes to any other project's
  files are rejected even though folder_policy declares them writable in principle.

Exception: explicit, user-approved ingestion may read source material. `Library/` is not promoted into the maintained wiki automatically.

Retention archives generated `Agent/Conversations/` projections after 30 days and may delete archived projections after 90 days only after durable memory distillation. Canonical chat history and pinned/keep notes are protected from silent deletion.

### Frontmatter Standard

Every file written by the agent must include YAML frontmatter:

```yaml
---
type: [agent-query | agent-response | agent-memory | agent-connection |
       agent-reflection | agent-digest | skill-proposal | saved-response]
created: YYYY-MM-DD
agent_version: vellum-1.0
private: true
---
```

### Wikilink Standard

Every file written by the agent should wikilink its source notes:

```markdown
## sources
- [[Books/meditations--marcus-aurelius/04-book-four|Book Four · Meditations]]
- [[Agent/Conversations/2026/01/Asked about stillness|asked about stillness · January]]
```

This makes the agent's work visible in the Obsidian graph view.

---

## 6. Coding Standards

### File Structure Conventions

```
agent/
├── graph/
│   └── agent.py              ← create_react_agent, system prompt, tool list
├── tools/                    ← one file per tool, @tool decorated functions
├── privacy/                  ← classifier, scrubber, metadata_strip
├── obsidian/                 ← vault.py, ingester.py, folder_policy.py, watcher.py
├── rag/                      ← embedder.py, store.py, reranker.py, graph_retriever.py
├── llm/                      ← openrouter.py (ZDR enforced)
├── mcp/                      ← client.py, filesystem_tools.py, apify_tools.py
├── memory/                   ← honcho_client.py, fts5.py, resolved.py, skills.py, sessions.py
├── usage/                    ← audit_log.py, suggestions.py, pricing.py
├── scheduler/                ← digest.py, reflection.py, skill_detector.py
├── tui/                      ← app.py, styles.tcss, widgets/, screens/
└── cli/                      ← ledger.py (the usage dashboard)
```

### The OpenRouter Rule

Every call to OpenRouter MUST include:
```python
"provider": {
    "data_collection": "deny",
    "order": ["Fireworks", "Together", "DeepInfra"],
}
```

No exceptions. If this line is missing from a call, the call is wrong.

### Logging Rule

Every agent turn writes one JSON line to `data/memory/audit_log.jsonl`.
Fields: `timestamp, thread_id, model, provider, prompt_tokens,
completion_tokens, total_tokens, cost_usd, latency_first_token_ms,
latency_total_ms, tools_called, privacy_class, outcome,
retrieval_confidence, followup_detected, saved, regenerated`.

No content (prompt text or response text) is ever written to the audit log.
Metadata only. The vault is where content lives.

### Shell Command Approval Rule

The agent NEVER runs a local shell command without explicit user approval
in the current session. If a task requires a shell command, the agent
proposes it in plain text, waits for the user to confirm, then executes.

This applies to: file deletion, directory creation outside `Agent/`,
any `pip install`, any `git` command, any subprocess call.

---

## 7. Model Routing

Three models in the stack. Each has a role.

| Model | Role | Use when |
|---|---|---|
| Gemma 4 31B (primary) | Deep reasoning, complex synthesis | Retrieval confidence < 0.75, multi-tool queries, book synthesis |
| Qwen 3.5 35B (fallback) | Broad coverage | Primary fails or returns error |
| Gemma 4 12B (fast) | Quick tasks | Retrieval confidence ≥ 0.85, fact extraction, skill detection, summarization |

Routing logic lives in `agent/usage/suggestions.py::route_model()`.
The function reads recent audit log data to calibrate thresholds.
It returns the model string to use for the current query.

---

## 8. Failure Modes & Responses

| Failure | Response |
|---|---|
| OpenRouter timeout | Retry once with fast model. If still fails: "Unreachable." |
| Presidio scrubbing error | Block the query. Return: "Withheld." |
| Qdrant connection refused | Fall back to FTS5 keyword search only. Log the failure. |
| MCP server unavailable | Return: "Unreachable." Log tool name and timestamp. |
| Vault path not found | Refuse to operate. Return: "Vault not found. Check configuration." |
| RED classification | Block. Return: "Withheld." One sentence. No explanation. |
| Retrieval confidence below threshold | Return: "Nothing on this in your library." |
| Skill file malformed | Skip the skill. Log the error. Do not crash. |
| FTS5 index stale | Use vector search only. Rebuild index at next nightly digest. |

Failure messages are always one word where possible. They are never apologetic.
They are never explained at length. The user can ask why if they want to know.
