# Changelog

All notable changes to Vellum will be documented in this file.

The project follows Semantic Versioning once tagged releases begin. Vellum is currently in alpha development and has no tagged release history yet.

## [Unreleased]

### Added

- Capability-discovery contract for the frontend/backend boundary through `/api/capabilities`.
- Stable API adapter pattern for the Vellum web UI.
- Memory Orchestrator surfaces for summaries, saved memories, archived memories, settings, dreaming runs, and conversation imports.
- Maintained Obsidian Knowledge Wiki under `Vault/Knowledge` with explicit trust, provenance, history, linting, and source-aware ingestion.
- Idempotent Obsidian conversation export and retention workflows.
- Profile-based specialist delegation runtime with isolated task packets.
- Profile-scoped specialist response cache with freshness classes and stale fallback behavior.
- Profile-only LLM specialist support with declarative YAML profiles.
- Delegation audit records without raw prompts or private context.
- OpenRouter routing resilience with credential pools, provider policy, fallback chains, health state, cooldowns, and settings UI support.
- Direct provider handling for configured OpenAI routes.
- Hermes-compatible `SKILL.md` package system for procedural memory.
- Approval-gated skill mutation coordinator with package validation, locking, snapshots, catalog updates, and audit records.
- Privacy-safe `/learn` and `skill_learn` workflows.
- Background skill signal detection and proposal flow.
- Canonical skill catalog with duplicate detection and usage intelligence.
- Recoverable skill curator maintenance.
- Secure multi-source Skills Hub and marketplace adapters, including bundle quarantine and security scans.
- Skills Hub UI surface and tests.
- Spotify plugin status, OAuth, playback, player action, and recovery support.
- Agent/tool capability services for memory, MCP, X, YouTube, and shared tool registry surfaces.
- Voice STT/TTS modules and API coverage.
- Computer-use routing, guarded sessions, native Windows driver components, and overlay/runtime tests.
- Coding session service and Codex/Claude adapter coverage.
- Telemetry and usage ledger support for provider/tool usage.

### Changed

- Consolidated chat history ownership around `data/ui/conversations.json` and `/api/conversations`, with Obsidian conversation notes as projections.
- Clarified that Knowledge Wiki pages are maintained synthesis and raw Library material requires explicit approved ingestion.
- Shifted procedural memory from legacy JSON skill records toward Hermes-compatible `SKILL.md` packages.
- Moved frontend integration toward capability-driven feature discovery instead of hardcoded endpoint assumptions.
- Updated memory/retrieval flows to keep current conversation context above older memory when conflicts exist.
- Updated Docker services so Honcho and PostgreSQL are the local service dependencies while vector storage is configured through embedded ChromaDB.
- Refined routing behavior so visible streamed output is not replayed through an automatic model switch.

### Fixed

- Spotify playback recovery on inactive devices.
- Provider routing and 404 handling.
- Routing settings control polish.
- Frontend/backend contract regressions covered by tests.
- Knowledge Wiki and conversation projection edge cases covered by regression tests.

### Security

- Enforced zero-data-retention OpenRouter routing controls.
- Added privacy scrubbing for skill authoring and learning flows.
- Added security checks for remote skill packages and marketplace sources.
- Kept skill deletion recoverable and approval-gated.

## Release History

No version has been tagged yet. The first release should move the verified entries above into a dated version section and create a fresh `[Unreleased]` section.
