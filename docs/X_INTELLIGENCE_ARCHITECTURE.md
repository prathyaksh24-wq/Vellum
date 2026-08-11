# X Intelligence Architecture

## Ownership

Vellum has one runtime path for X capabilities:

```text
VellumAgent
  -> x_agent tool
XAgent
  -> ToolRegistry
  -> XCapabilityService
  -> AgentReachXProvider or an explicitly enabled fallback
  -> KnowledgeToolObserver
  -> Knowledge Core
```

| Responsibility | Canonical owner |
| --- | --- |
| Agent routing and response shape | `backend/agent/agents/x_agent.py` |
| Capability registration, permissions, and provider selection | `backend/agent/tools/capabilities/x_service.py` |
| Authenticated local X reads and writes | `backend/agent/tools/capabilities/agent_reach_x_provider.py` |
| Normalized evidence and provenance | Knowledge Core |
| Successful tool-call observation | `backend/agent/knowledge/tool_observer.py` |
| Human-readable vault notes | Derived projection only |

The portable Agent-Reach plugin exposes this adapter. It is not a second runtime or data store.

## Provider Policy

Agent-Reach is the primary local connector. The xAI search fallback is disabled by default because it is a paid external dependency and may not be available for the active account. Enable it explicitly with `X_TOOL_ALLOW_XAI_FALLBACK=true` only when working xAI credentials and billing are present.

An Agent-Reach search error must not be hidden by an unrelated xAI billing error. Timeline, bookmarks, likes, profiles, individual post reads, and confirmed writes continue to use Agent-Reach independently of search availability.

The main model never calls `twitter-cli`, xAI, or X capability adapters directly.
It delegates X intent to `x_agent`, which invokes the canonical `XAgent` from the
shared specialist registry. The specialist prepares mutations and the dispatcher
executes only a stored pending action after a later explicit confirmation.

## Reliability Contract

- `twitter-cli` 0.8.6 or newer is required; the connector health response reports
  the detected and minimum versions.
- CLI processes are serialized across provider instances.
- Read operations retry once for transient failures. Search may use xAI only when
  the fallback is explicitly enabled.
- Write operations never retry automatically and never switch providers after an
  attempted write. This prevents duplicate posts or account actions after an
  ambiguous timeout or connection failure.
- Post editing is unsupported. Vellum does not emulate it with delete and repost.

## Canonical Data Rules

Knowledge Core is the canonical home for normalized X evidence. Obsidian remains an optional projection and review surface.

Every ingested record must include:

- stable source identity and source version
- event type and event timestamp when known
- capture timestamp
- source URL or archive locator
- connector and account provenance
- content hash for idempotency
- sensitivity and outbound-use policy

Likes, bookmarks, follows, views, and reposts are observations. They are not preferences, beliefs, style signals, or endorsements by default. Repeated behavior over time may support a derived signal, but the evidence and inference must remain separate.

## Legacy Writers

`scripts/poll_x.py` and `scripts/x_ingest.py` write directly to `Vault/Library/X`. Treat them as legacy migration inputs:

- do not extend them with new source types
- do not run them as a second canonical ingestion pipeline
- route future scheduled ingestion through the shared connector and Knowledge Core
- generate vault notes from canonical records after normalization

No Siftly code or store is part of this phase. Reassess its local bookmark UI and graph ideas only after the canonical X pipeline is operating and measured.

## Delivery Order

1. Keep the current X connector observable and fail accurately.
2. Add an immutable X archive adapter through the shared connector plugin.
3. Normalize posts, likes, bookmarks, follows, and account events into Knowledge Core with idempotent keys.
4. Add temporal interest, ambiguity, and sensitivity annotations without rewriting raw evidence.
5. Add incremental live enrichment through existing X tools and scheduled jobs.
6. Add frontend views for source health, evidence, derived interests, and provenance.
7. Add export to chat and coding agents through bounded context packs.

Each step requires focused contract tests, replay tests for duplicate input, privacy checks, and a canary run before enabling scheduled writes.
