# Vellum LLM Routing and Resilience Design

Date: 2026-07-01
Status: Approved for implementation planning

## Goal

Give Vellum a single production-grade backend for OpenRouter inference-provider routing, same-provider credential rotation, and ordered cross-model/provider fallback. The model selected in the existing frontend picker remains the primary model for every new turn. A minimal settings surface exposes configuration and operational status without committing to a final UI design.

## Scope

The first release provides:

- Global and per-model OpenRouter provider-routing policies.
- Credential pools for OpenRouter and direct OpenAI credentials.
- Ordered, turn-scoped fallback targets for OpenRouter and direct OpenAI models.
- One shared routing runtime for synchronous chat, streamed LangGraph chat, and background LLM calls.
- Durable policy, health, cooldown, and attempt metadata.
- Secret storage through the operating-system credential store, with environment credentials represented by references only.
- Redacted management and diagnostics APIs.
- Minimal settings controls and status displays.
- Automatic migration from the existing single-key and single-fallback configuration.

The provider abstraction must admit future Anthropic, Google, or custom OpenAI-compatible adapters without changing the routing engine. Those adapters are not part of this release.

## Existing behavior and migration constraints

Vellum currently has two independent OpenRouter paths:

1. `agent.graph.agent.build_llm()` constructs `ChatOpenAI` directly for the normal LangGraph agent. It adds privacy policy and a hard-coded upstream order for open-weight models.
2. `agent.llm.openrouter.openrouter_chat()` is a separate non-streaming helper with a single fallback model.

The normal agent builders intentionally call `build_llm()`, not the existing `build_llm_with_fallback()`. Therefore the current single fallback helper does not protect ordinary chat. The implementation must replace this split with one routing runtime rather than extending both paths independently.

Compatibility requirements:

- The existing model picker and `POST /api/settings/active-model` continue to select the primary model.
- Every new user turn starts with that selected primary model, even when the prior turn used a fallback.
- Existing `OPENROUTER_API_KEY` and `OPENAI_API_KEY` values seed their respective pools as reference-only credentials.
- Existing `FALLBACK_MODEL` becomes the first OpenRouter fallback only when no explicit fallback chain has been stored.
- Existing `PRIMARY_MODEL`, `FAST_MODEL`, ZDR, privacy scrubbing, checkpointing, tools, and chat response formats remain compatible.
- Direct `openai/*` routing continues to use OpenAI when a native OpenAI credential is configured; otherwise it remains eligible for OpenRouter.

## Architecture

The implementation has seven focused boundaries.

### Routing engine

The routing engine owns the attempt sequence for one logical model invocation. It receives an immutable request containing messages, tools, model parameters, streaming mode, thread ID, and the user-selected primary model. It resolves a turn plan, leases credentials, calls adapters, classifies failures, applies retries and cooldowns, and advances through fallback targets.

The engine must not contain provider-specific HTTP parsing. It consumes normalized adapter successes and `ProviderFailure` values.

### Provider adapters

An adapter converts a logical target into a provider client and normalizes provider results and errors. The first release includes:

- `OpenRouterAdapter`: supports routing policies, upstream-provider metadata, OpenRouter usage, and OpenAI-compatible chat semantics.
- `OpenAIAdapter`: supports native OpenAI models and usage metadata.

Adapters receive a resolved secret for one attempt. They never read the credential database directly.

### Credential pool

The credential pool selects and leases healthy credentials for a provider. It owns selection strategies, request counts, consecutive rate-limit state, cooldowns, invalid status, and startup reconciliation. Pool selection and state transitions are transactional.

Supported strategies:

- `fill_first`: use the highest-priority healthy credential until unavailable.
- `round_robin`: rotate across healthy credentials after each lease.
- `least_used`: select the healthy credential with the lowest successful-plus-failed request count.
- `random`: select uniformly from healthy credentials using a replaceable random source for deterministic tests.

Credentials are provider-scoped. An optional model allow-list can restrict a credential to specific model IDs, but OpenRouter credentials are usable across models by default.

### Policy stores

The routing policy store persists global defaults and per-model overrides. The fallback policy store persists an ordered list of targets. Both stores expose validated domain models rather than raw database records.

### Secret resolver

The secret resolver resolves either an environment-variable reference or an operating-system credential-store reference. Raw secrets exist only in memory for the duration of client construction/request execution. They are never returned by domain objects, serialized into SQLite, included in exceptions, or written to logs.

### Routed LangChain model

A routed chat-model wrapper implements the LangChain interfaces required by `create_react_agent`. Both synchronous and asynchronous agent builders receive this wrapper. It delegates complete logical invocations to the routing engine while preserving LangChain message, tool-call, usage, and streaming event semantics.

### Telemetry

Routing telemetry records content-free attempt data: thread ID, logical invocation ID, model, API provider, reported OpenRouter inference provider, credential fingerprint, attempt number, fallback index, latency, token usage, estimated cost, outcome, normalized failure class, and cooldown decision.

## Configuration model

### OpenRouter routing policy

A policy contains:

```yaml
sort: latency                 # price | latency | throughput | null
only: []                      # upstream inference-provider allow-list
ignore: []                    # upstream inference-provider deny-list
order: []                     # preferred upstream inference-provider order
require_parameters: true
allow_fallbacks: true         # OpenRouter upstream fallback, not model fallback
data_collection: deny
zdr: true
```

Global policy is merged with a per-model override. Scalar override values replace global values. List override values replace, rather than append to, global lists so the resulting request is predictable. `data_collection: deny` and `zdr: true` are mandatory Vellum privacy floors and cannot be weakened through the API.

Validation rules:

- `sort` accepts only `price`, `latency`, `throughput`, or null.
- Provider names are trimmed, non-empty, case-preserving strings and are compared case-insensitively for duplicates.
- A provider cannot appear in both `only` and `ignore`.
- When `only` is non-empty, every `order` entry must also appear in `only`.
- The generated OpenRouter `provider` body omits unset and empty optional fields.

### Fallback targets

A fallback target contains:

```yaml
provider: openrouter          # openrouter | openai
model: qwen/qwen3.5-35b-a3b
```

Targets are tried in stored order after the primary target is exhausted. Validation rejects missing providers/models, unsupported providers, exact duplicates, a target identical to the resolved primary target, and cycles introduced by future named chains. The first release stores one global chain; the schema includes stable target IDs so per-model chains can be added later without rewriting attempt telemetry.

The engine applies a configurable hard limit to total target attempts per invocation. The default is the primary plus three fallback targets. This bounds latency and prevents configuration mistakes from producing failover loops.

## Request lifecycle

For each logical model invocation:

1. Capture the model currently selected in the provider registry.
2. Resolve the primary API provider. An `openai/*` model uses native OpenAI when a healthy native credential exists; otherwise it uses OpenRouter. All other catalog models use OpenRouter in this release.
3. Build an immutable attempt plan containing the primary and validated fallback targets.
4. Merge global and per-model OpenRouter routing policy for each OpenRouter target.
5. Ask the credential pool for an eligible lease.
6. Resolve that lease's secret and invoke the provider adapter.
7. On success, commit usage and health metadata, release the lease, emit telemetry, and return the normalized result.
8. On failure, apply the failure policy, update credential/target state, release the lease, and retry or advance as directed.
9. When every allowed attempt is exhausted, raise a sanitized terminal routing error containing a correlation ID and normalized attempt summary, never raw provider response bodies or secrets.

Fallback is invocation-scoped and turn-scoped. It does not mutate the active model registry. Consequently, the next LLM invocation and the next user turn both begin from the selected primary model unless a single agent turn contains multiple model invocations, in which case each invocation independently starts with the primary target.

## Failure classification and recovery

Adapters classify failures into the following stable categories:

| Failure | Credential action | Target action |
| --- | --- | --- |
| Authentication, HTTP 401/403 | mark invalid; rotate immediately | retry target with another credential |
| Billing/quota, HTTP 402 | cool down 24 hours; rotate immediately | retry target with another credential |
| Definite plan/daily usage exhaustion | cool down using provider hint or 24 hours | retry target with another credential |
| Generic HTTP 429, first consecutive occurrence | no cooldown | retry same credential once after bounded delay |
| Generic HTTP 429, second consecutive occurrence | cool down 1 hour; rotate | retry target with another credential |
| HTTP 404/model unavailable | leave credential healthy | mark this target unavailable for the invocation and advance |
| HTTP 408/409/425 and network timeout | no credential penalty | bounded exponential retry on same target |
| HTTP 500/502/503/504 | no credential penalty | bounded exponential retry on same target |
| Malformed or empty response | no credential penalty on first occurrence | retry once, then advance target |
| Invalid request/unsupported parameters, other 4xx | leave credential healthy | fail invocation without fallback unless explicitly classified as target compatibility |

Retry delays use bounded exponential backoff with jitter and honor `Retry-After` when present. Tests inject a clock, sleeper, and random source; production code never relies on wall-clock sleeps in unit tests.

A successful request resets the credential's consecutive-429 state and records its last-success time. Cooldowns expire lazily during selection and can also be reset explicitly through the management API.

## Streaming and tool-call safety

Fallback is safe only before irreversible output becomes externally visible.

- Before the first text delta, tool-call delta, or completed tool request is emitted, the engine may retry credentials or switch targets.
- After any text or tool-call content is emitted, automatic cross-target fallback is disabled for that invocation.
- A post-emission provider failure ends the stream with a sanitized error event and correlation ID.
- The engine never replays a tool call automatically after a provider switch.

This policy favors correctness over hiding every outage. It prevents duplicated text, repeated writes, or repeated external tool actions.

## Persistence and concurrency

SQLite stores:

- Routing-policy documents and revisions.
- Ordered fallback targets.
- Credential metadata, source references, fingerprints, priorities, strategy counters, status, cooldowns, and timestamps.
- Content-free routing attempts and aggregate health data.
- A schema version and completed migrations.

Manual secrets are stored through the Python keyring API using the operating system's credential backend. Environment-derived credentials store only their environment-variable name and a non-reversible fingerprint. Startup reconciliation:

1. Adds or refreshes environment references that currently resolve.
2. Removes unavailable environment-derived entries after active leases finish.
3. Preserves manual keyring entries until explicitly removed.
4. Never copies an environment secret into keyring or SQLite.

Credential selection and mutation run under an in-process async lock plus SQLite transactions. A lease has an ID and expiry so an interrupted request cannot leave a credential permanently busy. Selection does not require exclusive use of a credential; leases provide concurrency accounting and prevent unsafe mutation/removal while requests are active. SQLite busy timeouts and short transactions support Vellum's API and background tasks without holding a database write lock across network calls.

## Backend API

The API surface is versioned under `/api/llm-routing`:

- `GET /status`: effective primary target, global policy summary, fallback chain, pool health counts, and latest routing outcome.
- `GET /policies`: global policy and per-model overrides.
- `PUT /policies/global`: validate and replace global policy.
- `PUT /policies/models/{model_id}`: validate and replace one model override.
- `DELETE /policies/models/{model_id}`: remove one override.
- `GET /fallbacks`: ordered fallback targets.
- `PUT /fallbacks`: validate and atomically replace the chain.
- `GET /credentials`: redacted credential metadata and pool strategies.
- `POST /credentials`: add a manual credential to keyring and metadata storage.
- `DELETE /credentials/{credential_id}`: remove a non-leased manual credential; environment credentials must be removed at their source.
- `PUT /credentials/{provider}/strategy`: change selection strategy.
- `POST /credentials/{provider}/reset`: clear cooldown and transient exhaustion state.
- `GET /attempts`: bounded, paginated, content-free routing diagnostics.

Mutation endpoints use strict Pydantic request models, reject unknown fields, and perform atomic replacement. Credential creation accepts a secret but never echoes it. All responses use generic redacted credential models. API exception handling removes authorization headers, raw response bodies, and secret-like substrings before logging.

The legacy `/api/settings/provider-key` endpoint remains operational during migration but becomes a compatibility wrapper that replaces or creates a single named manual credential. It is deprecated in response metadata and is not used by the new UI.

## Minimal settings UI

The existing settings screen receives a compact LLM Routing section. It is intentionally functional rather than final-design work.

It shows:

- The active model and resolved primary API provider.
- Effective provider-routing fields for the active model.
- The ordered fallback models.
- Credential counts by provider: healthy, cooling down, invalid, and total.
- The latest request route, whether fallback occurred, and a sanitized reason.

It provides basic controls to edit the routing policy, reorder fallback targets, add/remove manual credentials, select a rotation strategy, and reset cooldowns. It never renders full keys. After entry, a credential is represented by label and short fingerprint only. Existing model-picker behavior and layout remain unchanged.

## Observability and privacy

Every logical invocation receives a correlation ID. Every target and credential attempt receives a child attempt ID. Structured logs and SQLite telemetry contain IDs and normalized metadata only.

The following are prohibited from logs, telemetry, API responses, and UI state:

- Raw API keys or bearer tokens.
- Authorization headers.
- Prompt, message, tool argument, or response content.
- Raw provider error bodies.
- Local secret-store paths or operating-system credential payloads.

Credential fingerprints use a keyed or salted one-way digest and expose only a short display suffix through APIs. They are identifiers, not authentication material.

OpenRouter requests always enforce `data_collection: deny` and ZDR regardless of stored policy. Existing privacy classification and PII scrubbing occur before the routing engine receives messages.

## Testing strategy

All implementation follows red-green-refactor TDD. Tests use temporary SQLite databases, fake keyring backends, injected clocks/sleepers/randomness, and deterministic provider adapters.

Unit coverage includes:

- Policy validation and deterministic merge semantics.
- OpenRouter request-body generation for every routing field and privacy floor.
- Pool strategies, model eligibility, counters, cooldown expiry, removal, and startup reconciliation.
- Authentication, billing, rate-limit, unavailable-model, network, server, malformed-response, and invalid-request classification.
- Retry budgets, `Retry-After`, target ordering, attempt limits, and terminal error sanitization.
- Fallback-chain validation and legacy migration.
- Secret redaction and fingerprint stability without secret recoverability.
- Lease lifecycle, concurrent selection, expired-lease recovery, and SQLite transaction behavior.
- Streaming fallback before output and refusal to fallback after text/tool output.

Integration coverage includes:

- Normal `ainvoke` chat using credential rotation and fallback.
- `astream_events` preserving Vellum's existing SSE and activity-event shapes.
- Tool-calling responses and checkpoint history across a target switch.
- Background calls using the same engine and policies.
- Direct OpenAI primary/fallback and OpenRouter primary/fallback combinations.
- Active-model switching without changing persisted fallback policy.
- Redacted management endpoints and legacy endpoint compatibility.
- Minimal UI status loading and mutations against mocked APIs.

Regression verification runs the existing OpenRouter, provider registry, API model, chat streaming, telemetry, privacy, and agent tests in addition to the new suite.

## Operational behavior

- Routing database unavailability fails closed with a sanitized error; it does not silently bypass privacy or use an untracked key.
- Keyring unavailability leaves environment credentials usable and marks manual credentials unavailable without deleting metadata.
- Invalid policy rows encountered at startup are quarantined and the mandatory safe global default is used; a warning includes only row IDs and validation errors.
- Telemetry write failure does not fail a successful model response, but it emits a content-free operational warning.
- Policy updates are visible to new invocations without rebuilding the process. Active invocations retain their immutable attempt plan.
- Health and cooldown state survive application restarts.

## Acceptance criteria

- Selecting a model in the existing picker makes it the primary model for every new turn.
- OpenRouter receives the effective global-plus-model provider policy on every applicable request.
- Multiple OpenRouter or OpenAI credentials rotate according to strategy and failure policy.
- Exhausted primary credentials/routes trigger the configured ordered fallback chain without losing LangGraph conversation state.
- The next invocation starts from the selected primary model again.
- No cross-target retry occurs after streamed text or tool output becomes visible.
- Policies, fallback order, credential health, cooldowns, and telemetry persist across restarts.
- No secret or message content appears in SQLite metadata, logs, API responses, or UI state.
- Synchronous, asynchronous, streaming, background, and tool-calling paths use the same routing engine.
- The minimal settings surface can inspect and manage the supported backend configuration without altering the existing model picker.
- Existing chat, privacy, telemetry, and model-selection regression tests continue to pass.

## Non-goals

- Final visual design for routing settings.
- Native Anthropic, Google, or custom-endpoint adapters in the first release.
- Cross-region distributed credential coordination across multiple Vellum installations.
- Automatic provider benchmarking or autonomous cost/quality policy changes.
- Retrying or replaying tool calls after partial output.
- Circumventing provider quotas or terms of service; credential pools provide resilience for legitimately configured credentials.
