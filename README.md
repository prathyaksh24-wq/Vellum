# Vellum

Vellum is a privacy-first, local-first personal agent workspace. It combines a FastAPI agent backend, a Vite web interface, a Tauri desktop shell, Obsidian-backed memory and knowledge, model routing, tools, plugins, coding mode, computer-use foundations, and a Hermes-compatible skills system.

> [!WARNING]
> Vellum is in active alpha development. Features, data formats, APIs, and installation steps may change without notice.

## Current Status

Vellum is a development-stage personal agent runtime. The current implementation is focused on making the core loops reliable: chat, memory, model routing, retrieval, skills, plugins, coding workflows, knowledge management, and local privacy boundaries.

There are no tagged releases yet. The next release should be treated as the first documented alpha milestone.

## Principles

- Privacy first: classify and scrub sensitive input before model or tool use.
- Local first: keep memory, vault content, audit logs, skill packages, and local indexes on the user's machine.
- User-controlled data: Obsidian Markdown, SQLite databases, and local package directories remain inspectable and recoverable.
- Model flexible: route through OpenRouter, direct provider keys, local models, or configured specialists where supported.
- Transparent operation: expose tools, memory, usage, plugins, skills, and routing state through explicit contracts and logs.

## Current Capabilities

- Chat API and streaming responses through the FastAPI backend.
- Vite-powered web UI with a capability-discovery contract.
- Desktop shell and overlay foundations for local app workflows.
- OpenRouter model routing with credential pools, provider policy, fallback chains, cooldown handling, and zero-data-retention routing controls.
- Direct OpenAI provider support for configured `openai/*` models.
- Obsidian vault integration with folder policy, retention, conversation export, and user-readable memory projections.
- Memory Orchestrator for saved memory, summaries, settings, archived items, FTS5 search, Honcho integration, and provider extensions.
- Maintained Knowledge Wiki under `Vault/Knowledge`, separate from raw `Vault/Library` imports.
- Hermes-compatible `SKILL.md` package system with approval-gated mutations, catalog rebuilds, duplicate checks, usage intelligence, curator support, and a Skills Hub surface.
- Plugin surfaces for Spotify, memory, Agent Reach, portable plugins, and Hermes skills.
- Coding-assistant mode backed by Codex and Claude adapters.
- Computer-use routing, guarded sessions, native Windows drivers, and overlay support.
- Voice STT/TTS modules using Moonshine and Kokoro when enabled.
- MCP/tool integrations for filesystem, Apify, Playwright, GitHub, Obsidian, Context7, GitMCP, Context Mode, Tavily, Firecrawl, and web/search providers.
- Test coverage across API contracts, memory, routing, skills, computer use, coding mode, plugins, Spotify, voice, and tool boundaries.

## Experimental Or Incomplete Areas

- Public release packaging and upgrade flow.
- Cross-device support.
- Fully polished desktop distribution.
- Full voice conversation UX.
- Production-grade computer-use automation.
- Proactive assistance and autonomous routines beyond guarded local schedules.
- External plugin marketplace workflows beyond the current local and approved package flows.

## Architecture Overview

```text
frontend/ + design uploads      Web UI and adapter contracts
desktop/                        Tauri desktop shell and overlay surfaces
backend/agent/api.py            FastAPI application and HTTP/WebSocket routes
backend/agent/graph/agent.py    Main LangGraph agent
backend/agent/llm/              Provider and routing layer
backend/agent/memory/           Memory Orchestrator, Honcho, FTS5, sessions
backend/agent/obsidian/         Vault IO, Knowledge Wiki, retention, exports
backend/agent/skills/           Hermes skill packages, catalog, curator, hub
backend/agent/tools/            Agent tools and capability registry
backend/agent/coding/           Coding session service and adapters
backend/agent/computer_use/     Guarded desktop/browser/computer-use runtime
plugins/                        Portable connector and memory plugin packages
Vault/                          Local Obsidian vault used by Vellum
data/                           Local runtime stores, logs, indexes, caches
```

The frontend discovers backend surfaces through `GET /api/capabilities` and uses adapter modules rather than calling feature routes directly from view logic. See [Architecture](docs/ARCHITECTURE.md) and [Frontend/Backend Contracts](docs/architecture/frontend-backend-contracts.md).

## Development Setup

Vellum currently expects a local development environment.

Requirements:

- Python 3.11 or newer.
- Node.js and npm.
- Docker, for the self-hosted Honcho service.
- An Obsidian vault path configured in `.env`.
- Provider credentials for any cloud model or external connector you enable.

Typical Windows startup:

```powershell
.\scripts\start.ps1
```

This starts the API through `scripts/start-api.ps1`, then starts the Vite UI and prints the local UI/API URLs.

Backend-only startup:

```powershell
.\scripts\start-api.ps1
```

Frontend commands:

```powershell
npm --prefix frontend run dev
npm --prefix frontend run build
npm --prefix frontend test
```

Backend checks:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest
```

## Configuration

Configuration is read from `.env` at the repository root. Important settings include:

- `OPENROUTER_API_KEY`
- `OPENAI_API_KEY` when using direct OpenAI routes
- `OBSIDIAN_VAULT_PATH`
- `FILESYSTEM_MCP_PATH`
- `HONCHO_BASE_URL`
- `CHROMA_PATH`
- `ZDR_ONLY=true`
- `ENABLE_PII_SCRUBBING=true`
- provider and MCP keys for optional integrations

`docker-compose.yml` currently defines the local Honcho API and PostgreSQL database. Embedded vector storage is configured through ChromaDB.

## Privacy Model

Vellum treats privacy as part of the runtime boundary:

- User input is classified as RED, YELLOW, or GREEN before model use.
- YELLOW input is scrubbed locally with Presidio-style anonymization.
- RED input is blocked.
- Folder policy controls which vault content may be sent to a model.
- Raw `Vault/Library` content is not automatically promoted into the maintained Knowledge Wiki.
- Audit logs store metadata, not prompt or response content.
- OpenRouter calls are configured for zero-data-retention routing.
- Local memory, skill packages, usage records, and knowledge files remain on the user's machine.

## Documentation

- [Changelog](CHANGELOG.md)
- [Roadmap](ROADMAP.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Personal Intelligence Architecture](docs/PERSONAL_INTELLIGENCE_ARCHITECTURE.md)
- [Memory and Knowledge Ownership](docs/memory-knowledge-architecture.md)
- [Knowledge Wiki](docs/knowledge-wiki.md)
- [Skills System](docs/SKILLS_SYSTEM.md)
- [Skills Operations](docs/SKILLS_OPERATIONS.md)
- [Frontend/Backend Contracts](docs/architecture/frontend-backend-contracts.md)

## Known Limitations

- Vellum is not production-ready.
- The repository has no formal tagged release history yet.
- Some older documentation still exists as operational reference and may include historical design notes.
- The desktop shell, voice mode, and computer-use flows are still alpha surfaces.
- External connectors require local credentials and may be unavailable without provider setup.
- Documentation and architecture should be reviewed before each tagged release.

## Contributing

Keep changes small, testable, and aligned with the existing privacy and capability boundaries. When behavior changes, update the relevant documentation and add a `CHANGELOG.md` entry under `[Unreleased]`.
