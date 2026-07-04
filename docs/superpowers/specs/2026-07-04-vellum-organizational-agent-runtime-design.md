# Vellum Organizational Agent Runtime Design

## Purpose

Evolve Vellum's current profile and delegation layer into a supervised organizational agent runtime. Vellum remains the only user-facing routing agent. Specialists become independent workers with durable identities, private memory, skills, tools, workspaces, budgets, and opinions. Departments and temporary task rooms provide explicit collaboration without implicit memory overlap.

The design extends the existing SportsAgent, XAgent, YoutubeAgent, MemoryAgent, profile registry, Memory Orchestrator, cache, tool registry, and frontend streaming contract. Existing casual conversation and direct Vellum answers remain unchanged.

## Architectural Invariant

Vellum owns the relationship with the user and always produces the final user-facing response.

Vellum is responsible for:

- per-turn intent classification
- direct answers and casual conversation
- specialist and department selection
- task decomposition and task-room creation
- minimum-context handoffs
- cancellation and interruption
- evidence, freshness, confidence, and safety validation
- conflict resolution and synthesis
- shared-memory promotion decisions
- user-visible progress and final responses

Specialists never replace the main conversation or write directly to the frontend.

## Goals

- Give each agent a durable, independently configurable identity.
- Load each agent's SOUL, personality, skills, instructions, tools, and memory inside its worker.
- Isolate workers in supervised subprocesses by default.
- Support an optional container backend for high-risk profiles.
- Prevent direct access to other agents' private state.
- Provide explicit department, organization, and task-room collaboration scopes.
- Enforce iteration, timeout, concurrency, and delegation-depth limits.
- Support single, parallel, department, and nested delegation.
- Propagate cancellation through complete task trees.
- Keep Vellum responsive to unrelated and casual turns while specialists work.
- Preserve existing deterministic handlers and confirmation behavior.

## Non-goals

- Making every ordinary request a group task.
- Giving every agent the complete parent conversation.
- Allowing agents to browse arbitrary private memories.
- Replacing Vellum with a peer-to-peer swarm.
- Treating personality as authority to override safety or evidence.
- Requiring containers for lightweight trusted specialists.
- Automatically promoting specialist opinions into organization memory.

## Approaches Considered

### Same-process logical profiles

The current approach is inexpensive and compatible, but a shared Python process cannot strongly isolate environment variables, working directories, terminal state, failures, or direct client access. It remains useful as a compatibility fallback, not the target runtime.

### Subprocess actor runtime

Each agent runs as a supervised actor with a private home, explicit RPC contract, restricted environment, brokered capabilities, independent lifecycle, and durable state. This provides the required cognitive and operational separation without the overhead of a container for every lightweight task. This is the default.

### Container per agent

Containers provide the strongest filesystem and process boundary but add startup cost, image management, Windows/Docker dependencies, and operational complexity. The same worker protocol will support `isolation: container` for coding, browser, or untrusted-tool profiles. Container profiles fail closed when Docker is unavailable unless an explicit fallback is configured.

## Organizational Model

```text
Vellum organization
|-- organization vision, safety, and reviewed shared memory
|-- Sports department
|   |-- department charter and memory
|   `-- SportsAgent
|-- Social department
|   |-- department charter and memory
|   |-- XAgent
|   `-- YoutubeAgent
|-- Memory department
|   `-- MemoryAgent
`-- temporary task rooms
    `-- explicitly selected cross-department participants
```

An agent belongs to one primary department and may participate in explicitly created task rooms. Department membership grants department-memory access; it never grants access to another member's private memory.

## Agent Home

Each agent has a stable home independent of its working directory:

```text
data/agents/<agent-id>/
|-- profile.yaml
|-- SOUL.md
|-- AGENTS.md
|-- personalities/
|   |-- default.md
|   |-- reviewer.md
|   `-- creative.md
|-- skills/
|-- memory/
|   |-- private.db
|   `-- cache.db
|-- sessions/
|-- workspace/
`-- audit/
```

The supervisor creates missing directories and starter identity files. Existing user files are never overwritten.

## Identity and Prompt Stack

Hermes's identity model is adopted with Vellum-specific organization layers.

### SOUL.md

`SOUL.md` is the durable primary identity and occupies prompt slot one. It defines voice, values, judgment, disagreement style, uncertainty handling, stable preferences, and personality-level behavior.

Rules:

- Load only from the agent home, never the launch or task directory.
- Inject exactly once.
- Seed a starter file only when missing.
- Never overwrite an existing file.
- Use a built-in profile identity when missing, empty, unsafe, or unreadable.
- Apply prompt-injection scanning and a configured size limit.
- Record the content hash and version in the run audit.

### AGENTS.md

`AGENTS.md` contains department and project operating instructions: architecture, conventions, tools, commands, workflows, paths, evidence requirements, and escalation rules. It does not define the durable personality.

### Personality overlays

Named files under `personalities/` provide temporary task or session modes. An overlay may adjust tone or reasoning posture but cannot override safety, capability, memory, or isolation policy. The active overlay and hash are recorded per run.

### Prompt order

1. Agent `SOUL.md`
2. Organization safety and vision
3. Department charter
4. Profile capabilities and budgets
5. Private agent memory
6. Department and reviewed organization memory
7. Task-room messages and permitted references
8. Skills
9. `AGENTS.md`
10. Timestamp and platform formatting
11. Temporary personality overlay

## Profile Schema

The current profile schema is extended:

```yaml
version: 2
id: SportsAgent
department: sports
description: Sports research, schedules, results, and analysis
executor: hybrid
model: openrouter/auto
isolation:
  backend: subprocess
  container_image: null
  allow_fallback: false
identity:
  soul: SOUL.md
  agents: AGENTS.md
  default_personality: default
skills:
  directories: [skills]
tools:
  allow: [sports.search, web.search]
memory:
  private_scope: agent:SportsAgent
  read_scopes: [agent:SportsAgent, department:sports, organization:shared]
  publish_to: [department:sports]
  organization_writes: propose_only
delegation:
  role: leaf
  max_iterations: 30
  timeout_seconds: 600
  max_concurrent_children: 0
  max_spawn_depth: 1
workspace:
  filesystem_roots: [workspace]
  terminal: dedicated
```

Unknown fields are rejected. Version-one profiles receive a deterministic compatibility migration in memory and are not rewritten automatically.

## Executor Types

### Deterministic

Mechanical acquisition or mutation using existing Python handlers. Deterministic handlers receive a typed `AgentExecutionContext`, not only a string query. The context contains the profile, parsed skill directives, task metadata, budgets, permitted memory references, department charter, and cancellation token.

Natural-language identity files cannot magically change deterministic code. Deterministic handlers consume structured directives only. SOUL and personality still inform Vellum's attributed synthesis of the result.

### LLM

A fresh model invocation with the full approved prompt stack and brokered tools. It receives no parent transcript unless Vellum explicitly includes selected messages.

### Hybrid

The preferred mode for SportsAgent, XAgent read operations, YoutubeAgent, and judgment-heavy specialists. The existing deterministic handler gathers data and evidence; an isolated profile LLM reasons over that structured result using its identity, skills, and memory. If model execution is unavailable, the deterministic response remains a clearly identified fallback. Confirmed X mutations remain deterministic and skip LLM processing.

Cache lookup occurs before either stage. Successful hybrid results cache the final structured response and retain the acquisition evidence.

## Worker Protocol

Workers communicate with the supervisor using versioned JSON messages over private local IPC. Subprocess workers use authenticated local pipes; container workers use an authenticated loopback transport with a per-run token.

Request envelope:

```json
{
  "protocol_version": 1,
  "run_id": "run-123",
  "task_id": "task-456",
  "parent_task_id": null,
  "agent_id": "SportsAgent",
  "department": "sports",
  "goal": "Compare the title race scenarios",
  "context_refs": ["task-room:room-7:message-2"],
  "personality": "reviewer",
  "budgets": {"iterations": 30, "deadline": "..."},
  "capability_token": "opaque"
}
```

Workers return structured progress, tool requests, messages, memory proposals, and a final `SpecialistResponse`. Raw credentials and unrestricted paths never cross the protocol.

## Supervisor

`AgentSupervisor` owns worker lifecycle and task trees.

Responsibilities:

- spawn and authenticate subprocess/container workers
- maintain heartbeats and lifecycle state
- enforce deadlines and iteration limits
- enforce global, department, parent, and profile concurrency
- issue cancellation tokens and propagate cancellation recursively
- terminate stuck workers and descendants
- restart reusable workers after crashes
- preserve deterministic batch result order
- collect cost, tokens, tools, sources, files, identity hashes, and status
- keep worker failure isolated from Vellum and siblings

Workers do not directly spawn operating-system children for delegation. Orchestrator workers request child tasks from the supervisor, which validates role, depth, and concurrency policy.

## Isolation and Capability Brokers

Subprocess isolation uses a sanitized environment, dedicated current directory, private agent home, and supervisor-issued capability token. Environment variables are allowlisted; provider credentials remain in the supervisor's credential system.

All sensitive operations are brokered:

- `ToolBroker`: validates profile tool allowlist, existing agent permissions, confirmations, and task token.
- `MemoryBroker`: validates owner, department, task room, scope, and requested operation.
- `FilesystemBroker`: validates canonical paths against granted roots and blocks traversal/symlink escapes.
- `TerminalBroker`: owns one terminal namespace per worker and enforces workspace roots.
- `NetworkBroker`: applies profile domain/provider policy where supported.
- `CredentialBroker`: provides operation-scoped credentials without exposing the credential pool.

Direct clients in existing agents are migrated behind brokers. SportsAgent no longer calls its web client outside the tool policy. Compatibility direct calls are disabled in supervised mode.

Subprocess isolation is an application boundary, not an operating-system security sandbox. Profiles that execute untrusted code or require stronger filesystem guarantees use the container backend.

## Memory Governance

Memory scopes are explicit:

- `agent:<id>`: private to one agent
- `department:<id>`: visible to department members
- `organization:shared`: reviewed organization knowledge
- `task-room:<id>`: visible only to room participants for the room lifetime
- `public-source:<domain>`: reusable source evidence
- `proposal:<id>`: awaiting promotion review

Every record contains owner, visibility, provenance, evidence, confidence, timestamps, profile version, retention policy, and source task.

Cross-scope movement is an explicit promotion operation:

```text
private observation
  -> department proposal
  -> MemoryAgent/Vellum review
  -> department or organization publication
```

Search never changes visibility. Recipients receive permitted memory records or references, never access to another agent's database. Conflicting claims remain separately attributed until reviewed.

Existing centralized memory is treated as organization/shared compatibility data. New private writes go to per-agent stores. Migration uses dual-read and new-store-first-write until compatibility data is explicitly classified.

## Departments and Task Rooms

Departments provide a charter, member registry, memory scope, tool policy ceiling, and concurrency budget. Individual profiles can only narrow department policy.

Task rooms provide temporary cross-agent collaboration. A room records participants, purpose, permitted scopes, messages, artifacts, deadline, and retention action. Room members see only messages and explicitly attached references.

On completion, a task room is:

- distilled into attributed proposals and durable artifacts
- archived for audit when policy requires
- otherwise deleted after its retention period

## Agent Communication

Agents communicate through typed supervisor messages:

```yaml
message_id: msg-1
sender: ResearchAgent
recipient: department:marketing
task_id: task-123
type: evidence_proposal
claim: The campaign performed best in segment A.
evidence_refs: [artifact:report-9]
confidence: 0.86
visibility: task-room:launch-review
```

Supported message types include question, evidence proposal, critique, decision proposal, artifact reference, clarification request, and final contribution.

Messages are immutable, attributed, scope-checked, and auditable. Agents may disagree. Vellum preserves material disagreements and may request a reviewer rather than forcing artificial consensus.

## Delegation Modes

### Direct

Vellum delegates one focused task to one specialist.

### Parallel batch

Vellum submits independent tasks concurrently. Results are returned in input order regardless of completion order. A batch larger than its configured limit is rejected rather than truncated.

### Department fan-out

Vellum creates a task room and requests contributions from selected department members. This is reserved for tasks needing multiple viewpoints.

### Nested orchestration

Profiles with `role: orchestrator` may request children through the supervisor. Depth is checked against organization and profile limits. Leaf profiles cannot delegate.

Most user turns use no specialist or one specialist. Group execution is not the default.

## Cancellation and Responsiveness

Each task tree owns a cancellation token. Cancellation occurs when:

- the user stops the task
- Vellum supersedes it with a replacement request
- a deadline or iteration limit is exceeded
- the supervisor detects a stale heartbeat
- a parent task fails under fail-fast policy

Cancellation propagates to descendants and active broker calls. Workers receive a grace period, then are terminated. Siblings continue unless batch policy is fail-fast.

Long-running delegation executes outside Vellum's conversational turn. The frontend can continue sending unrelated or casual messages. Vellum may report progress, cancel the old task, or allow it to continue according to user intent. Completed background work returns as a routed event and is synthesized by Vellum.

## Cache Behavior

The existing profile-scoped cache remains the first execution gate. Cache entries include profile, identity, skill-set, department-charter, and executor-version hashes. Changes to any behavior-bearing input invalidate the entry.

Writes, memory mutations, live intent, and non-idempotent operations bypass cache. Stale fallback remains available for failed refreshes and is clearly labeled.

## Frontend Contract

The frontend continues to chat only with Vellum. Existing response events remain compatible. Additive events expose task trees, departments, workers, progress, messages, cancellation, disagreements, and synthesis state.

The frontend never needs to know worker transport details. A specialist result is never rendered as the final assistant response until Vellum synthesizes it.

## Error Handling

- Invalid identity or skill file: reject unsafe content and use the last-known-good or built-in fallback.
- Worker startup failure: retry within budget, then use compatible in-process fallback only when profile policy permits.
- Missing Docker for container profile: fail closed unless explicit fallback is configured.
- Heartbeat timeout: cancel descendants, terminate worker, and return structured failure.
- Broker denial: return a permission error without widening policy.
- Memory-scope violation: deny, audit, and do not reveal record existence.
- Partial batch failure: return successful siblings and attributed failures unless fail-fast is configured.
- Conflicting results: preserve claims and evidence; request review or report uncertainty.
- Vellum synthesis failure: retain specialist results and allow synthesis retry without repeating completed work.

## Compatibility

- `LiveAgentDispatcher.maybe_handle()` remains the routing entry point during migration.
- Existing `SpecialistResponse` remains the final specialist contract.
- Existing deterministic `answer(query)` handlers use a compatibility adapter until migrated to `answer_task(context)`.
- Existing X confirmation and pending-action behavior remains outside cache and LLM replay.
- Existing skill routing remains valid.
- Existing organization memory and Obsidian notes remain readable.
- Existing frontend chat, casual conversation, and streaming events remain valid.
- In-process execution remains an explicit compatibility backend, never the default for version-two profiles.

## Observability

Audits record:

- route and routing reason
- task tree and task-room membership
- agent, department, profile, identity, personality, skill, and executor hashes
- isolation backend and worker lifecycle
- cache decision
- message and memory-reference IDs
- tool, terminal, filesystem, and network broker decisions
- iterations, deadlines, heartbeats, cancellation, and exit reason
- model, token, cost, sources, confidence, and artifacts

Prompt bodies, credentials, private memory contents, and raw task-room content are excluded from general logs.

## Testing Strategy

### Identity and skills

- agent-home-only SOUL loading
- starter creation without overwrite
- empty/unsafe fallback
- single prompt injection
- AGENTS and personality precedence
- security scanning and truncation
- skill discovery, validation, activation, and hash invalidation

### Isolation

- environment allowlist
- working-directory and agent-home separation
- path traversal and symlink escape denial
- credential non-disclosure
- direct-client denial in supervised mode
- subprocess crash containment
- optional container availability and fail-closed behavior

### Memory and communication

- private memory non-discoverability
- department and organization scope checks
- task-room participant checks and expiry
- explicit promotion workflow
- immutable attributed messages
- conflicting-claim preservation

### Delegation

- direct, parallel, department, and nested modes
- deterministic result ordering
- concurrency and depth rejection
- iteration and wall-clock timeout enforcement
- heartbeat detection
- recursive cancellation and sibling policy
- background task continuity with unrelated casual chat

### Compatibility

- Sports, X, YouTube, and Memory behavior
- X confirmations and non-replay
- cache hit, bypass, invalidation, and stale fallback
- existing API and frontend events
- old profile migration
- fallback behavior under unavailable worker/model/container

## Delivery Sequence

1. Identity, skill, and version-two profile loading.
2. Typed execution context and deterministic/hybrid migration.
3. Scoped memory stores, departments, task rooms, and message bus.
4. Subprocess worker protocol and capability brokers.
5. Budgets, heartbeats, cancellation, parallel batches, and nested orchestration.
6. Optional container backend.
7. Frontend progress/task-tree events, compatibility cleanup, and full evaluation.

Each sequence step must leave existing chat and specialists operational. Compatibility fallbacks are removed only after equivalent supervised paths pass integration tests.
