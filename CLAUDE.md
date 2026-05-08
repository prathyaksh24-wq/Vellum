# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: Vellum

Privacy-first, Obsidian-native LangGraph personal agent. Answers come from the user's local Obsidian vault first; the LLM (OpenRouter) is treated as untrusted and folder-level policy gates what content ever leaves the machine.

## Common commands

All commands assume the repo root [`/Users/macbookair/Desktop/Vellum`](./). The Python venv lives at `.venv/` and the backend is import-rooted at `backend/`.

**API (FastAPI + LangGraph)**
- Start: `bash scripts/start-api.sh` — uses `.venv/bin/python`, runs `uvicorn agent.api:app` with `PYTHONPATH=backend`, defaults to `127.0.0.1:8000`. Wraps in `screen` if available; writes pid/log/status to `.api-runtime/`.
- Stop: `bash scripts/stop-api.sh`
- Health: `curl http://localhost:8000/api/health`
- Direct (no script): `PYTHONPATH=backend .venv/bin/python -m uvicorn agent.api:app --reload`
- CLI chat (alternative entrypoint): `PYTHONPATH=backend .venv/bin/python -m agent.cli` (also exposed as `personal-agent` script per `pyproject.toml`).

**UI**
- Static fallback server (Node, no deps): `bash scripts/start.sh` → `http://localhost:4242` serving [frontend/ui/vellum-chat.html](frontend/ui/vellum-chat.html). API calls return stubs; pair with the API on `:8000` for real data.
- Vite dev (React): `cd frontend && npm run dev` → `http://127.0.0.1:5173`.
- Vite build: `cd frontend && npm run build` → `frontend/ui-dist/`.

**Tests**
- Full suite: `cd backend && ../.venv/bin/pytest` (pytest config in [backend/pyproject.toml](backend/pyproject.toml) sets `testpaths=["tests"]`, `pythonpath=["."]`).
- Single test: `cd backend && ../.venv/bin/pytest tests/test_rag.py::test_name -v`

**Qdrant (only if `QDRANT_LOCAL_PATH` is unset)**
- `docker compose up -d qdrant` — exposes 6333/6334, persists to `data/embeddings/qdrant/`.
- Default config uses embedded `QdrantClient(path=...)` against `data/embeddings/qdrant-local/`, so Docker is normally not needed.

## Architecture

### Request flow (`/api/chat`)
1. `agent.api` → `LazyAgent.ainvoke` ([backend/agent/graph/agent.py](backend/agent/graph/agent.py)) builds an async LangGraph `create_react_agent` lazily (one-time init), backed by an `AsyncSqliteSaver` at [data/memory/checkpoints.db](data/memory/) for thread-keyed conversation state.
2. The ReAct loop chooses among 7 tools wired in [backend/agent/graph/agent.py](backend/agent/graph/agent.py#L93): `search_my_notes`, `web_search`, `search_amazon`, `read_file`, `list_files`, `create_note`, `append_to_note`. The system prompt forces vault-first behavior.
3. After answering, `_background_learn` fires a fire-and-forget task that classifies the exchange, scrubs PII if YELLOW, drops it entirely if RED, and writes a Q&A note + extracts ≤2 facts via the fast model.

### Privacy is enforced in three independent layers
This is the load-bearing invariant of the codebase. Touching any of these without understanding the others will break the privacy contract.

1. **Folder policy** ([backend/agent/obsidian/folder_policy.py](backend/agent/obsidian/folder_policy.py)) — the source of truth for what may leave the machine. Folders map to `{STORED, INDEXED, SENT_TO_LLM, TOOL_ACCESSIBLE}` permission sets. `X`, `Youtube`, `Books`, `feedback` are local-only (indexed but never sent to OpenRouter raw); `Sports/*` and `Agent` may go to the LLM. Anything unknown defaults to `PRIVATE_LOCAL_ONLY`. Any new retrieval/tool path **must** call `can_send_to_llm` / `filter_chunks_for_llm` before assembling LLM context.
2. **PII classifier** ([backend/agent/privacy/classifier.py](backend/agent/privacy/classifier.py)) — RED/YELLOW/GREEN. RED (secrets, gov IDs, credit cards) blocks storage and LLM transit. YELLOW triggers Presidio scrubbing. GREEN passes through.
3. **OpenRouter ZDR** ([backend/agent/graph/agent.py:60-65](backend/agent/graph/agent.py#L60)) — `extra_body={"provider": {"data_collection": "deny", "zdr": True}}`. `ZDR_ONLY=true` is enforced in `Settings.validate_paths_and_privacy`; do not flip it.

### Vault ingestion (RAG)
- Chunking + embedding lives in [backend/agent/obsidian/ingester.py](backend/agent/obsidian/ingester.py) (400-word chunks, 50 overlap). Embedder uses `BGE-M3` via `sentence-transformers`; reranker is `cross-encoder/ms-marco-MiniLM-L-6-v2` ([backend/agent/tools/vault_search.py](backend/agent/tools/vault_search.py#L28)) with a lexical fallback if the model is unavailable.
- Vector store wraps `qdrant-client` ([backend/agent/rag/store.py](backend/agent/rag/store.py)). Two collections: `obsidian_vault`, `agent_queries`. Metadata strip (frontmatter, `[[wikilinks]]` provenance) happens in [backend/agent/privacy/metadata_strip.py](backend/agent/privacy/metadata_strip.py) before vectors are written.
- Reindex from API: `POST /api/vault/reindex`. From CLI: `/reindex`.

### Persistence layout (under `data/`, all gitignored)
- `data/memory/checkpoints.db` — LangGraph `AsyncSqliteSaver` thread state.
- `data/memory/long_term.db` — `LongTermMemory` SQLite (facts + query log) used by background learning and `/api/memory/*`.
- `data/embeddings/qdrant-local/` — embedded Qdrant storage.

### Background services
- `start_scheduler` (APScheduler) — nightly digest summarizes recent facts via the fast model and writes a markdown note to the `Agent/` vault folder.
- `start_vault_watcher` (watchdog) — debounced reindex on vault file changes; debounce in `VAULT_WATCHER_DEBOUNCE_SECONDS`.
Both are started in the FastAPI `lifespan` and shut down on app exit.

### Frontend
- Two parallel UIs live in `frontend/`:
  - [frontend/ui/vellum-chat.html](frontend/ui/vellum-chat.html) — vanilla static HTML/JS chat, served by `scripts/start.sh`.
  - React/Vite app rooted at `frontend/ui/` (entry referenced in [frontend/vite.config.mjs](frontend/vite.config.mjs)) plus components under `frontend/components/`.
- The CORS allowlist on the API ([backend/agent/api.py:64](backend/agent/api.py#L64)) covers ports `4242` (static UI) and `5173` (Vite). Add new dev origins there, not via wildcard.

## Configuration

All settings load via `pydantic-settings` from [.env](./) into [backend/agent/config.py](backend/agent/config.py). Notable invariants enforced at startup:
- `OBSIDIAN_VAULT_PATH` and `FILESYSTEM_MCP_PATH` must exist; the MCP path **must be inside** the vault (sandboxing).
- `ZDR_ONLY` must remain `true`.
- `MIN_RETRIEVAL_SCORE` ∈ [0,1]; `MAX_CONTEXT_CHUNKS ≥ 1`; `MAX_CONTEXT_TOKENS ≥ 1`.

`get_settings()` is `@lru_cache`'d — settings are loaded once per process. Tests should construct fresh `Settings(...)` instances rather than rely on the singleton.

## Conventions worth knowing

- **Import root**: backend code uses absolute imports from `agent.*`. Always run with `PYTHONPATH=backend` (the start scripts do this; tests get it via `pytest.ini_options.pythonpath`).
- **Tools are LangChain `@tool`s**, not graph nodes. Privacy lives *inside* the tool (see [backend/agent/tools/vault_search.py](backend/agent/tools/vault_search.py)) — there is no separate access-control node, despite what the build plan hints. New tools must enforce folder policy themselves.
- **MCP**: filesystem and Apify MCP clients live in [backend/agent/mcp/](backend/agent/mcp/). Apify Amazon results are treated as private (paraphrased, never quoted) per the system prompt.
- The repo is currently **not a git repository** (no `.git/`). If asked to commit, initialize one first or check with the user.

## Reference docs

- [docs/langgraph-agent-build-plan.md](docs/langgraph-agent-build-plan.md) — original full spec. The implementation has drifted (e.g., access control is in tools, not its own node) — treat the code as authoritative when they disagree.
- [docs/build-plan-changes.md](docs/build-plan-changes.md) — change log relative to the spec.
