# Vellum Architecture

This document is the high-level architecture guide for the current Vellum implementation. Deeper operational details live in `AGENTS.md`, `docs/AGENT_ARCHITECTURE.md`, `docs/SKILLS_SYSTEM.md`, and the feature-specific docs linked from the README.

## System Shape

Vellum is a local-first agent workspace with four main layers:

- Frontend and desktop surfaces for chat, tools, settings, skills, memory, plugins, terminal, coding, and workspace interaction.
- FastAPI backend exposing stable HTTP, streaming, and WebSocket contracts.
- Agent runtime for model routing, LangGraph execution, tools, specialists, memory, skills, and guarded computer-use flows.
- Local storage in the repository, Obsidian vault, SQLite databases, ChromaDB, Honcho/PostgreSQL, package directories, and audit logs.

## Frontend

The production web UI is exposed through the design-upload/Vite pipeline and is described by `GET /api/capabilities`.

The capability contract declares:

- canonical frontend entry path
- available feature surfaces
- plugin-owned capabilities
- endpoint paths
- supported chat stream event names

Frontend view code should use adapter modules under `frontend/ui/api/` or the design-upload API adapters. It should not hardcode raw backend routes inside UI components.

## Backend

The backend entry point is `backend/agent/api.py`. It defines the FastAPI app, chat routes, streaming routes, settings routes, plugin routes, coding routes, terminal routes, memory routes, Knowledge Wiki routes, Spotify routes, voice routes, computer-use routes, and capability discovery.

Important backend modules:

- `backend/agent/contracts/` for stable response contracts.
- `backend/agent/graph/` for the main LangGraph agent.
- `backend/agent/llm/` for provider and routing behavior.
- `backend/agent/memory/` for memory orchestration and session state.
- `backend/agent/obsidian/` for vault access, retention, and Knowledge Wiki.
- `backend/agent/skills/` for procedural memory and Skills Hub services.
- `backend/agent/tools/` for model-callable tools and capability registry.

## Desktop Runtime

The `desktop/` directory contains the Tauri desktop shell and overlay-related surfaces. The backend also includes computer-use workspace and overlay modules for guarded local interaction. Desktop functionality is still an alpha surface.

## Agent Runtime

The main agent is built around LangGraph and tool calling. Vellum routes user turns through:

1. privacy classification and scrubbing
2. memory and knowledge retrieval
3. model/provider routing
4. tool and specialist dispatch
5. streaming response delivery
6. storage, audit, and memory update hooks

The runtime also supports specialist delegation. Declarative profiles can define executor type, tool policy, memory scope, cache policy, and delegation limits. Each delegation run receives a bounded task packet instead of inheriting the entire parent conversation.

## Model Providers

OpenRouter is the main cloud model route. Vellum stores routing state in `data/llm-routing/routing.db` and supports:

- credential pools
- provider allow/deny/priority policy
- fallback chains
- cooldowns for failed or exhausted credentials
- zero-data-retention routing controls
- active model settings

Direct OpenAI routes are available when configured for `openai/*` models. Their privacy behavior follows the direct provider rather than OpenRouter.

## Memory System

Vellum separates memory into several layers:

- Current conversation state through API/session storage.
- Canonical chat history in `data/ui/conversations.json`.
- Memory Orchestrator data and settings in local stores.
- FTS5 search for keyword recall.
- Honcho for local user modeling, backed by PostgreSQL in Docker.
- Obsidian conversation projections for user-readable history.
- Saved and archived memory surfaces.

Current conversation context wins when it conflicts with older memory.

See `docs/memory-knowledge-architecture.md` for the ownership contract.

## Knowledge System

The Personal Intelligence Knowledge Core is the target canonical evidence layer.
It stores source identity, immutable versions, observations, provenance,
relationships, temporal preferences, projections, and context-package lineage.
It currently runs additively in shadow mode.

The Knowledge Wiki remains a maintained Obsidian synthesis layer under
`Vault/Knowledge` during migration. It is separate from raw `Vault/Library`
material and will become the optional Karpathy-style projection after cutover.

Normal wiki operations read and write maintained Knowledge pages. Raw Library content is read only when explicitly approved for a specific ingestion request. Pages carry trust and provenance metadata, and revisions are versioned under the wiki history directory.

See `docs/knowledge-wiki.md` and `docs/PERSONAL_INTELLIGENCE_ARCHITECTURE.md`.

## Tools And MCP Integrations

Tool implementations live under `backend/agent/tools/` and MCP wrappers live under `backend/agent/mcp/`.

Supported integration areas include:

- filesystem access scoped to the configured vault path
- Apify-backed scraping workflows
- Playwright browser inspection/control
- GitHub and local git helpers
- Obsidian API access
- Context7 and GitMCP documentation lookup
- Context Mode execution and retrieval
- Tavily, Firecrawl, SerpAPI, DuckDuckGo, and web extraction helpers
- X, YouTube, Sports, Spotify, terminal, coding, voice, and computer-use tools

Tool exposure is controlled through registry and capability services. Mutating or destructive operations are guarded by configuration and policy.

## Plugin System

Plugins are exposed as capability-owned feature surfaces. Current plugin areas include Spotify, Memory Orchestrator, Agent Reach, portable plugin discovery, and Hermes skills.

The frontend should discover plugin availability through the capability contract and plugin endpoints rather than assuming all plugin routes are available.

## Skills System

Procedural memory is stored as Hermes-compatible `SKILL.md` packages under the `.skills/` tree. The package tree is canonical; catalog databases are rebuildable projections.

Skill lifecycle operations use the mutation coordinator:

- stage
- privacy check
- validation
- security scan
- per-skill locking
- approval
- atomic publish
- catalog update
- audit record

See `docs/SKILLS_SYSTEM.md` and `docs/SKILLS_OPERATIONS.md`.

## Computer-Use Modes

Computer-use modules support guarded local workflows, browser/desktop routing, input guards, session state, screenshots, overlays, and native Windows driver components. These surfaces are still alpha and should remain explicit and observable.

## Coding-Assistant Mode

Coding mode is separate from default chat. It has its own session service, event model, storage, and adapters for Codex and Claude. The frontend consumes coding-specific events rather than treating coding mode as a normal chat stream.

## Data Storage

Important local storage locations:

- `data/ui/conversations.json` for canonical conversations.
- `data/knowledge/core.db` and `data/knowledge/blobs/` for the shadow Personal Intelligence store.
- `data/memory/` for memory databases, logs, and derived stores.
- `data/llm-routing/routing.db` for routing state.
- `data/skills/catalog.db` for the skills catalog projection.
- `.skills/` for canonical skill packages and snapshots.
- `Vault/` for Obsidian content, Knowledge Wiki pages, and agent projections.
- `data/embeddings/chroma` for embedded ChromaDB vector storage when enabled.
- Docker `honcho_data` volume for Honcho's PostgreSQL database.

## Privacy Boundaries

Vellum's privacy gate classifies user input before model use:

- RED input is blocked.
- YELLOW input is scrubbed locally.
- GREEN input can proceed with query tagging.

Folder policy controls vault context injection. Private or raw source folders may contribute to local retrieval decisions without sending raw content to a model unless a specific policy permits it.

Audit logs store metadata, not prompt or response content. Skills, memory, and knowledge workflows avoid storing raw private task text in catalog metadata or usage logs.

## Local Versus Cloud Processing

Local processing includes privacy classification, scrubbing, Obsidian IO, SQLite/FTS5 storage, ChromaDB storage, Honcho, package/catalog operations, conversation exports, and audit logs.

Cloud or external calls occur only when configured features require them:

- model calls through OpenRouter or direct providers
- external connector APIs such as Spotify, Apify, SerpAPI, X, GitHub, Tavily, or Firecrawl
- hosted documentation MCP services such as Context7 and GitMCP

External calls should receive only the minimum approved and scrubbed context needed for the operation.

## High-Level Request Flow

```text
User input
  -> FastAPI request or stream route
  -> privacy classification and scrubbing
  -> conversation/session lookup
  -> memory and Knowledge Wiki retrieval
  -> folder policy and context shaping
  -> model/provider route selection
  -> LangGraph agent invocation
  -> tool or specialist dispatch as needed
  -> streaming response events
  -> telemetry and audit metadata
  -> conversation, memory, and projection updates
```

The frontend consumes semantic stream events such as `response.output_text.delta`, `response.output_item.added`, and `response.completed`, with legacy compatibility events handled only as fallback where still supported.
