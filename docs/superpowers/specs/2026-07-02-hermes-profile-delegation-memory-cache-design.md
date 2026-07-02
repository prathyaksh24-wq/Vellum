# Vellum Profile Delegation and Memory Cache Design

## Purpose

Extend Vellum's existing Master/Pupil runtime with Hermes-inspired persistent agent profiles, isolated delegation runs, and cache-first specialist retrieval. Existing agents, routing entry points, response contracts, Obsidian storage, tool confirmation behavior, and fallback paths must remain compatible.

The target model separates two concepts:

- An agent profile is persistent configuration: identity, executor, instructions, tools, skills, memory policy, cache policy, and delegation limits.
- A delegation run is ephemeral execution: one explicit goal and context packet, isolated from the parent's conversation, with its own run record and result.

Existing SportsAgent, XAgent, YoutubeAgent, and MemoryAgent remain deterministic by default. Future profiles can opt into an independent LLM executor.

## Goals

- Preserve current behavior when no profile files exist.
- Make agent capabilities declarative and inspectable.
- Give each delegated task a fresh context and stable run identity.
- Check profile-approved Obsidian memory before calling live tools.
- Apply domain-aware freshness rules instead of reusing semantically similar but stale answers.
- Return the existing `SpecialistResponse` shape for both cache hits and live execution.
- Keep Vellum responsible for routing, safety, validation, and final synthesis.
- Support future agents without adding new hard-coded orchestration branches.

## Non-goals

- Replacing Vellum's Memory Orchestrator or Obsidian vault.
- Creating a separate operating-system account, process, gateway, or home directory per profile.
- Moving credentials into profile files.
- Changing existing X write confirmation semantics.
- Enabling recursive delegation for current specialists.
- Converting current deterministic agents into mandatory LLM calls.

## Approaches Considered

### Full Hermes-style installation per agent

Each agent would receive separate configuration, credentials, state database, service process, and home directory. This provides strong operational isolation but duplicates Vellum infrastructure and creates high compatibility and migration risk.

### Metadata-only profile wrappers

Profiles would describe existing agents, but delegation would continue as a direct method call. This is low risk but does not establish a durable run model, cache gate, or future LLM executor boundary.

### Hybrid profile runtime

Profiles describe persistent policy while a delegation runtime executes either an existing deterministic handler or an optional fresh LLM worker. This preserves current behavior and provides the extension points needed for future agents. This is the selected approach.

## Architecture

### ProfileRegistry

`ProfileRegistry` loads versioned YAML profile definitions from `data/agent_profiles/`. Every built-in specialist also has a Python default. A missing file uses the default; an invalid file is rejected and the safe default is used with an audit warning.

Profile files contain no credentials. Provider keys, credential pools, and model routing remain controlled by Vellum's existing routing runtime.

### AgentProfile

The profile schema contains:

```yaml
version: 1
id: SportsAgent
description: Sports research, schedules, results, and analysis
executor: deterministic
instructions: profiles/sports/SOUL.md

tools:
  allow:
    - web.search
    - sports.search
  require_confirmation: []

skills:
  directories:
    - profiles/sports/skills

memory:
  read_scopes:
    - user_profile
    - shared
    - agent:SportsAgent
  write_scope: agent:SportsAgent
  shared_writes: propose_only
  cache_first: true

cache:
  default_ttl_seconds: 21600
  live_ttl_seconds: 120
  historical_ttl_seconds: 2592000
  bypass_terms:
    - live
    - latest
    - today
    - now

delegation:
  max_iterations: 30
  timeout_seconds: 0
  can_delegate: false
```

The schema is strict at its boundary but applies safe defaults for optional fields. Unknown executors, invalid scopes, negative TTLs, and malformed tool policies invalidate the file and trigger built-in fallback.

### DelegationRuntime

`DelegationRuntime` becomes the single execution boundary used by `LiveAgentDispatcher`. It receives a selected agent, its profile, the user goal, explicit context, parent thread ID, and optional task ID.

Each invocation creates a `DelegationRun` with:

- run ID
- parent thread ID
- selected profile ID and version
- executor type
- goal and explicit context
- cache decision and reason
- start and finish timestamps
- tools and sources used
- status and normalized result

The deterministic executor calls the existing agent's `answer()` method. It does not receive the parent transcript. The future LLM executor creates a new agent/checkpointer context and receives only the profile prompt, goal, explicit context, and profile-approved memory.

Current leaf profiles cannot delegate. The data model retains a `can_delegate` flag so controlled nested orchestration can be introduced later without changing profile format.

### Routing Integration

`LiveAgentDispatcher` remains the API entry point. Its route selection order becomes:

1. Resolve an active routing skill through `SkillRouteResolver`.
2. Resolve the named agent from `PupilRegistry`.
3. Fall back to existing deterministic `can_handle()` matching.
4. Return control to Vellum when no specialist matches.

The existing pending X action confirmation path runs before new routing and is unchanged.

### Memory Cache Gate

The Memory Orchestrator gains specialist cache methods rather than a second memory subsystem.

Before execution, `DelegationRuntime` requests a cache decision using:

- profile ID
- normalized query
- parent thread ID
- allowed read scopes
- cache policy
- current time

The result is one of:

- `hit`: relevant, valid, fresh, and readable by the profile
- `miss`: no sufficiently relevant result
- `stale`: relevant result exists but has expired
- `bypass`: policy requires live execution

The cache stores a serialized `SpecialistResponse` plus:

- canonical query and normalized fingerprint
- profile ID and profile version
- captured and expiry timestamps
- freshness class
- confidence
- source URLs and timestamps
- result hash

Exact normalized fingerprints are the first lookup. Related-query lookup may use existing FTS retrieval, but a semantic match never overrides expiry or live-intent policy.

### Freshness Policy

Profiles provide defaults, while a classifier selects a freshness class:

- `live`: scores, active events, breaking news, current status
- `default`: schedules, standings, injuries, recent uploads, timelines
- `historical`: completed event summaries, historical statistics, transcript summaries

Explicit live intent bypasses cache by default. A profile can use a short live TTL when it has authoritative timestamped data. Stale entries remain available as fallback evidence if live execution fails, but the returned response must be marked stale.

### Persistence

Successful non-error responses are persisted after validation. The existing Memory Orchestrator continues recording turns, durable cards, FTS documents, and Obsidian artifacts. The new specialist cache stores normalized response metadata in the existing memory data area and links to Obsidian evidence.

Specialist write ownership follows `memory.write_scope`. Shared memory is proposal-only unless Vellum or MemoryAgent promotes it. Vellum may read specialist scopes for synthesis; unrelated specialists cannot read another specialist's private scope unless a profile explicitly grants it.

Cache persistence failures are logged but do not fail the user request.

### Result Handling

Both cached and live paths return `SpecialistResponse`. `LiveAgentResult` gains compatible optional metadata for confidence, run ID, cache status, and cache reason. Existing consumers that only read current fields continue working.

Vellum synthesizes specialist results as it does today. Existing X passthrough remains initially for compatibility, including confirmation and pending-action handling.

## Data Flow

```text
User message
  -> LiveAgentDispatcher checks pending confirmed actions
  -> routing skill or deterministic match selects a pupil
  -> ProfileRegistry loads the selected AgentProfile
  -> DelegationRuntime creates an isolated DelegationRun
  -> Memory Orchestrator evaluates the profile-scoped cache
       -> hit: deserialize SpecialistResponse
       -> miss/stale/bypass: execute configured specialist
  -> validate SpecialistResponse
  -> persist cache entry, run audit, turn, and memory proposals
  -> return LiveAgentResult
  -> Vellum validates and synthesizes the user-facing answer
```

## Compatibility and Migration

- Built-in profiles are available without filesystem setup.
- Existing `PupilRegistry.default()` remains valid.
- Existing specialist classes and `answer(query)` protocol remain valid.
- Existing API and streaming event shapes remain valid; new metadata is additive.
- Existing tool permission checks remain authoritative.
- Existing X pending action tables and confirmation flow are unchanged.
- Existing Obsidian content is not migrated or rewritten.
- Existing Memory Orchestrator settings continue to control whether new memory is stored.
- Cache lookup failures degrade to the original live execution path.
- Profile parse failures degrade to built-in safe defaults.

## Error Handling

- Unknown routed agent: ignore the invalid route, audit it, and use deterministic matching.
- Invalid profile: use built-in default and expose diagnostics through logs/status APIs.
- Cache backend failure: execute the specialist normally.
- Invalid cached payload: mark it unusable and execute normally.
- Specialist failure with stale cache: return the stale result with `status=stale` and reduced confidence.
- Specialist failure without cache: preserve the existing error/fallback response.
- Unauthorized tool: preserve `ToolPermissionError`; never widen the profile dynamically.
- Timeout: supported by the run contract; zero means no hard timeout.

## Observability

Delegation audit records include route source, profile version, executor, cache status, latency, tools, sources, and final status. Existing subagent streaming items remain, with additive run/cache metadata where available.

No prompt bodies, credentials, or unredacted private context are written to general logs.

## Testing Strategy

Tests will be written before implementation and cover:

- built-in profile defaults
- valid YAML override loading
- malformed profile fallback
- deterministic executor compatibility
- fresh run IDs and explicit context isolation
- skill route precedence and invalid-route fallback
- exact cache hits
- stale cache behavior
- explicit live bypass
- profile-version invalidation
- profile memory scope enforcement
- successful response persistence
- cache failure degradation
- stale fallback after live failure
- unchanged X confirmation flow
- unchanged default specialist behavior without profile files
- existing specialist, memory, routing, and API regression suites

## Why This Improves on a Direct Hermes Copy

Hermes profiles isolate whole agent installations and Hermes delegated workers are ephemeral. Vellum combines the useful parts while retaining its local-first knowledge system:

- Persistent specialist identity without duplicating the entire application installation.
- Fresh task context without discarding domain memory.
- Obsidian-backed, human-readable specialist knowledge.
- Domain-aware cache freshness that avoids unnecessary model and API calls.
- Deterministic low-token executors for tasks that do not require another model.
- An opt-in LLM executor for future judgment-heavy profiles.
- One safety, routing, credential, and synthesis authority under Vellum.

This produces a profile system tailored to Vellum rather than a filesystem-level clone of Hermes.
