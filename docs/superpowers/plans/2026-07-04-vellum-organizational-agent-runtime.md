# Vellum Organizational Agent Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Vellum's profile runtime into a supervised organization of individually stateful specialist actors with explicit identity, skills, scoped collaboration, subprocess/container isolation, brokered capabilities, bounded parallel/nested delegation, cancellation, and frontend observability.

**Architecture:** Vellum remains the only user-facing router and final responder. Version-two profiles create stable agent homes; workers communicate with an `AgentSupervisor` through typed messages, while supervisor-owned brokers enforce memory, tools, files, terminals, network, credentials, budgets, and task-tree policy. Existing deterministic specialists migrate through a typed execution context and hybrid mode without breaking current chat, cache, X confirmation, or streaming behavior.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLite, multiprocessing/subprocess, asyncio, JSONL/JSON-RPC, LangChain chat models, FastAPI/SSE, standalone HTML/JavaScript frontend, pytest.

---

## Delivery Boundaries

This plan has four independently verifiable phases:

1. Identity, skills, version-two profiles, typed contexts, and hybrid reasoning.
2. Scoped organization memory, departments, task rooms, and typed messages.
3. Supervisor, subprocess/container workers, brokers, budgets, cancellation, parallelism, and nesting.
4. API/streaming/frontend integration and full regression verification.

Every task retains the in-process compatibility path until the supervised equivalent passes its focused tests.

## File Map

- `backend/agent/profiles/models.py`: version-two profile, identity, isolation, workspace, department, and delegation policy.
- `backend/agent/profiles/home.py`: stable agent-home creation and starter seeding.
- `backend/agent/profiles/identity.py`: SOUL/AGENTS/personality loading, scanning, truncation, and prompt assembly.
- `backend/agent/profiles/skills.py`: agent-home skill discovery, validation, activation, and hashes.
- `backend/agent/agents/context.py`: typed `AgentExecutionContext` and compatibility adapter.
- `backend/agent/master/hybrid.py`: deterministic acquisition plus isolated profile reasoning.
- `backend/agent/organization/models.py`: departments, messages, task rooms, memory records, and promotions.
- `backend/agent/organization/store.py`: SQLite organization state.
- `backend/agent/organization/memory.py`: scope-enforcing memory broker.
- `backend/agent/organization/messages.py`: typed immutable communication and promotion workflow.
- `backend/agent/runtime/protocol.py`: worker request/event protocol.
- `backend/agent/runtime/worker.py`: subprocess worker entry point and broker proxies.
- `backend/agent/runtime/supervisor.py`: worker lifecycle, task trees, heartbeats, budgets, and cancellation.
- `backend/agent/runtime/backends.py`: in-process, subprocess, and container launch backends.
- `backend/agent/runtime/brokers.py`: tool, filesystem, terminal, network, credential, and model brokers.
- `backend/agent/runtime/orchestrator.py`: direct, parallel, department, and nested delegation.
- `backend/agent/master/runtime.py`: compatibility facade over the new orchestrator.
- `backend/agent/api.py`: organization, task, cancellation, and profile endpoints plus additive SSE events.
- `design/Velllum/uploads/Vellum Default Re-designed.html`: required task-tree and department UI target.

### Task 1: Version-Two Profiles and Stable Agent Homes

**Files:**
- Modify: `backend/agent/profiles/models.py`
- Modify: `backend/agent/profiles/registry.py`
- Create: `backend/agent/profiles/home.py`
- Modify: `backend/agent/profiles/__init__.py`
- Test: `backend/tests/test_agent_profiles_v2.py`

- [ ] **Step 1: Write failing version-two migration and home tests**

Create tests asserting:

```python
def test_v1_profile_migrates_in_memory_without_rewriting_file(tmp_path):
    path = tmp_path / "SportsAgent.yaml"
    original = "version: 1\nid: SportsAgent\nexecutor: deterministic\n"
    path.write_text(original, encoding="utf-8")
    profile = ProfileRegistry(profile_dir=tmp_path).get("SportsAgent")
    assert profile.version == 2
    assert profile.department == "sports"
    assert profile.isolation.backend == "subprocess"
    assert path.read_text(encoding="utf-8") == original


def test_agent_home_seeds_identity_without_overwrite(tmp_path):
    home = AgentHomeManager(tmp_path).ensure("SportsAgent")
    assert (home / "SOUL.md").exists()
    assert (home / "AGENTS.md").exists()
    (home / "SOUL.md").write_text("Custom identity", encoding="utf-8")
    AgentHomeManager(tmp_path).ensure("SportsAgent")
    assert (home / "SOUL.md").read_text(encoding="utf-8") == "Custom identity"
```

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_profiles_v2.py -q`

Expected: FAIL because version-two policy and `AgentHomeManager` do not exist.

- [ ] **Step 3: Extend the profile schema**

Add strict models:

```python
class IdentityPolicy(ProfileModel):
    soul: str = "SOUL.md"
    agents: str = "AGENTS.md"
    default_personality: str = "default"
    max_identity_chars: int = Field(default=12000, ge=1000, le=50000)

class IsolationPolicy(ProfileModel):
    backend: Literal["in_process", "subprocess", "container"] = "subprocess"
    container_image: str | None = None
    allow_fallback: bool = False

class WorkspacePolicy(ProfileModel):
    filesystem_roots: list[str] = Field(default_factory=lambda: ["workspace"])
    terminal: Literal["none", "dedicated"] = "dedicated"
    network_domains: list[str] = Field(default_factory=list)
```

Extend `AgentProfile` with `department`, `identity`, `isolation`, and `workspace`; extend executor to `deterministic | llm | hybrid`; extend delegation with `role`, `max_concurrent_children`, and `max_spawn_depth`. Built-ins use departments `sports`, `social`, `social`, and `memory`; trusted compatibility profiles may explicitly use `in_process`, while migrated defaults use subprocess.

- [ ] **Step 4: Implement in-memory v1 migration and stable homes**

`ProfileRegistry` must call `_migrate_profile_dict()` before validation. Migration fills version-two fields without changing the YAML file. `AgentHomeManager.ensure()` creates `memory`, `sessions`, `workspace`, `audit`, `skills`, and `personalities`, then seeds non-empty `SOUL.md`, `AGENTS.md`, and `personalities/default.md` only when absent.

- [ ] **Step 5: Run focused and legacy profile tests**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_profiles_v2.py tests/test_agent_profiles.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/agent/profiles backend/tests/test_agent_profiles_v2.py
git commit -m "feat: add versioned agent homes"
```

### Task 2: SOUL, AGENTS, Personality, and Skill Loading

**Files:**
- Create: `backend/agent/profiles/identity.py`
- Create: `backend/agent/profiles/skills.py`
- Modify: `backend/agent/profiles/__init__.py`
- Test: `backend/tests/test_agent_identity.py`
- Test: `backend/tests/test_agent_profile_skills.py`

- [ ] **Step 1: Write failing identity precedence and security tests**

Tests must prove agent-home-only resolution, exactly-once SOUL injection, missing/empty fallback, file truncation, blocked traversal, basic prompt-injection rejection, AGENTS placement, personality overlay placement, and stable hashes:

```python
stack = IdentityLoader(home).load(profile, personality="reviewer")
assert stack.sections[0].kind == "soul"
assert sum(section.kind == "soul" for section in stack.sections) == 1
assert stack.sections[-1].kind == "personality"
assert "ignore previous instructions" not in stack.render().casefold()
assert stack.identity_hash == IdentityLoader(home).load(profile, personality="reviewer").identity_hash
```

- [ ] **Step 2: Write failing agent-home skill tests**

Use markdown skills with YAML frontmatter containing `id`, `description`, `triggers`, `negative_triggers`, `priority`, and instructions. Assert safe path resolution, deterministic ordering, activation by current goal, negative-trigger exclusion, duplicate-ID rejection, size limits, and a combined `skill_hash`.

- [ ] **Step 3: Run and verify RED**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_identity.py tests/test_agent_profile_skills.py -q`

Expected: FAIL on missing modules.

- [ ] **Step 4: Implement loaders and prompt stack**

Create immutable `PromptSection(kind, content, source_hash)` and `IdentityStack`. Security scanning rejects null bytes, traversal, and instruction-override patterns targeting system/safety/capabilities. Truncation appends a visible marker. Skill activation uses explicit case-insensitive trigger phrases; it does not use network embeddings.

Render sections in the approved prompt order. Identity and skills are loaded only from the resolved agent home.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_identity.py tests/test_agent_profile_skills.py -q`

Expected: PASS.

```powershell
git add backend/agent/profiles backend/tests/test_agent_identity.py backend/tests/test_agent_profile_skills.py
git commit -m "feat: load per-agent identity and skills"
```

### Task 3: Typed Execution Context and Hybrid Specialists

**Files:**
- Create: `backend/agent/agents/context.py`
- Create: `backend/agent/master/hybrid.py`
- Modify: `backend/agent/agents/base.py`
- Modify: `backend/agent/agents/sports.py`
- Modify: `backend/agent/agents/x_agent.py`
- Modify: `backend/agent/agents/youtube.py`
- Modify: `backend/agent/agents/memory_agent.py`
- Modify: `backend/agent/master/runtime.py`
- Test: `backend/tests/test_agent_execution_context.py`
- Test: `backend/tests/test_hybrid_specialists.py`

- [ ] **Step 1: Write failing execution-context tests**

Define the desired contract:

```python
@dataclass(frozen=True)
class AgentExecutionContext:
    run_id: str
    task_id: str
    parent_task_id: str | None
    goal: str
    explicit_context: str
    profile: AgentProfile
    prompt_stack: IdentityStack
    skills: tuple[ActivatedSkill, ...]
    memory_refs: tuple[str, ...]
    task_room_id: str | None
    deadline: datetime | None
    max_iterations: int
    cancellation: CancellationView
```

Assert legacy agents still work through `answer(query)`, migrated agents receive `answer_task(context)`, and context contains no parent transcript.

- [ ] **Step 2: Write failing hybrid tests**

Assert deterministic acquisition runs once, the profile model receives the structured acquisition result plus identity/skills/memory, confirmed X writes skip the LLM stage, empty/model-failure falls back to the deterministic result, and final cache storage uses the hybrid response.

- [ ] **Step 3: Run and verify RED**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_execution_context.py tests/test_hybrid_specialists.py -q`

Expected: FAIL on missing context/hybrid modules.

- [ ] **Step 4: Implement compatibility and hybrid execution**

Add `ContextAwareSpecialist` protocol with `answer_task`. `invoke_specialist()` calls `answer_task` when present and otherwise calls `answer(context.goal)`. Update current specialists to accept context and consume structured skill directives where relevant.

`HybridExecutor` runs acquisition, serializes `SpecialistResponse` without action requests, invokes a fresh model with the prompt stack, then returns a response retaining original sources, activity events, memory proposals, and acquisition confidence. It never replays mutation actions.

- [ ] **Step 5: Run specialist regressions and commit**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_execution_context.py tests/test_hybrid_specialists.py tests/test_specialist_agents.py tests/test_x_tool.py -q`

Expected: PASS.

```powershell
git add backend/agent/agents backend/agent/master backend/tests/test_agent_execution_context.py backend/tests/test_hybrid_specialists.py
git commit -m "feat: add context-aware hybrid specialists"
```

### Task 4: Organization, Department, and Private Memory Scopes

**Files:**
- Create: `backend/agent/organization/__init__.py`
- Create: `backend/agent/organization/models.py`
- Create: `backend/agent/organization/store.py`
- Create: `backend/agent/organization/memory.py`
- Modify: `backend/agent/memory/orchestrator.py`
- Test: `backend/tests/test_organization_memory.py`

- [ ] **Step 1: Write failing scope and non-disclosure tests**

Test `agent`, `department`, `organization`, `task-room`, `public-source`, and `proposal` scopes. Assert an unauthorized search returns an empty result indistinguishable from absence; direct ID lookup raises a generic denial without revealing metadata; department members cannot see private peer memory; Vellum and MemoryAgent require explicit review authority for promotion.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_organization_memory.py -q`

Expected: FAIL on missing organization modules.

- [ ] **Step 3: Implement immutable memory records and broker**

Use SQLite tables for `memory_records`, `memory_evidence`, `memory_promotions`, and `scope_memberships`. `MemoryRecord` includes owner, scope, provenance, evidence references, confidence, profile version, retention, created/updated timestamps, and status.

`MemoryBroker.search(actor, scopes, query)` intersects requested scopes with memberships. `promote()` creates a new versioned record and immutable audit edge; it never updates visibility in place.

- [ ] **Step 4: Integrate Memory Orchestrator compatibility**

Existing global/user/project memory remains `organization:shared` compatibility data. New specialist writes go to `agent:<id>`. `build_memory_packet(read_scopes=...)` reads broker-approved records first and only includes legacy data for explicitly mapped organization scopes.

- [ ] **Step 5: Run memory regressions and commit**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_organization_memory.py tests/test_memory_orchestrator.py tests/test_memory.py -q`

Expected: PASS.

```powershell
git add backend/agent/organization backend/agent/memory/orchestrator.py backend/tests/test_organization_memory.py
git commit -m "feat: enforce organizational memory scopes"
```

### Task 5: Task Rooms, Messages, and Promotion Review

**Files:**
- Create: `backend/agent/organization/messages.py`
- Modify: `backend/agent/organization/models.py`
- Modify: `backend/agent/organization/store.py`
- Test: `backend/tests/test_task_rooms.py`
- Test: `backend/tests/test_agent_messages.py`

- [ ] **Step 1: Write failing room and message tests**

Assert only participants can read/write a room, messages are immutable and attributed, recipients receive permitted references instead of sender memory, unsupported visibility is denied, rooms expire, and completion produces proposals/artifacts before archive/delete.

Test message types `question`, `evidence_proposal`, `critique`, `decision_proposal`, `artifact_reference`, `clarification_request`, and `final_contribution`.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_task_rooms.py tests/test_agent_messages.py -q`

Expected: FAIL on missing APIs.

- [ ] **Step 3: Implement task-room and message services**

Create `TaskRoomService.create`, `add_participant`, `post`, `list_messages`, `complete`, and `expire`. Store messages with UUID, sender, recipient, task, type, claim, evidence references, confidence, visibility, and timestamp. Database triggers or update guards prevent content mutation.

`complete()` returns attributed memory proposals and artifact references; it does not automatically publish organization memory.

- [ ] **Step 4: Run and commit**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_task_rooms.py tests/test_agent_messages.py tests/test_organization_memory.py -q`

Expected: PASS.

```powershell
git add backend/agent/organization backend/tests/test_task_rooms.py backend/tests/test_agent_messages.py
git commit -m "feat: add scoped agent collaboration rooms"
```

### Task 6: Brokered Capabilities and Direct-Client Removal

**Files:**
- Create: `backend/agent/runtime/__init__.py`
- Create: `backend/agent/runtime/brokers.py`
- Modify: `backend/agent/tools/registry.py`
- Modify: `backend/agent/tools/capabilities/registry.py`
- Modify: `backend/agent/agents/sports.py`
- Test: `backend/tests/test_runtime_brokers.py`
- Test: `backend/tests/test_sports_broker.py`

- [ ] **Step 1: Write failing broker security tests**

Assert capability tokens bind agent/run/task/expiry; tool policy only narrows; confirmations remain required; filesystem canonicalization rejects traversal and symlink escape; terminal sessions have dedicated roots; network domains use allowlists; credentials are operation-scoped and never serialized; expired/revoked tokens fail generically.

- [ ] **Step 2: Write failing SportsAgent mediation test**

Construct SportsAgent in supervised mode with a broker proxy and a direct web searcher that raises if called. Assert `sports.search` is invoked through the broker and a disallowed profile cannot search.

- [ ] **Step 3: Run and verify RED**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_runtime_brokers.py tests/test_sports_broker.py -q`

Expected: FAIL on missing brokers and direct SportsAgent call.

- [ ] **Step 4: Implement brokers**

Create `CapabilityGrant` and supervisor-owned `ToolBroker`, `MemoryBrokerAdapter`, `FilesystemBroker`, `TerminalBroker`, `NetworkBroker`, `CredentialBroker`, and `ModelBroker`. Every request validates token, actor, task, scope, expiry, and policy before dispatch.

Register `sports.search` in the shared capability registry and migrate SportsAgent supervised execution to `ToolRegistry.invoke`. Compatibility direct search remains available only outside supervised context.

- [ ] **Step 5: Run capability regressions and commit**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_runtime_brokers.py tests/test_sports_broker.py tests/test_tool_registry.py tests/test_shared_capability_registry.py tests/test_specialist_agents.py -q`

Expected: PASS.

```powershell
git add backend/agent/runtime backend/agent/tools backend/agent/agents/sports.py backend/tests/test_runtime_brokers.py backend/tests/test_sports_broker.py
git commit -m "feat: broker specialist capabilities"
```

### Task 7: Versioned Worker Protocol and Subprocess Backend

**Files:**
- Create: `backend/agent/runtime/protocol.py`
- Create: `backend/agent/runtime/worker.py`
- Create: `backend/agent/runtime/backends.py`
- Test: `backend/tests/test_worker_protocol.py`
- Test: `backend/tests/test_subprocess_backend.py`

- [ ] **Step 1: Write failing protocol tests**

Test strict Pydantic validation for `run`, `progress`, `heartbeat`, `tool_request`, `tool_result`, `model_request`, `model_result`, `message`, `memory_proposal`, `result`, `error`, and `cancel`. Reject unknown versions/fields and mismatched run/task IDs.

- [ ] **Step 2: Write failing subprocess isolation tests**

Start a test worker and assert sanitized environment, dedicated cwd/home, no credential variables, authenticated first message, heartbeat output, broker round trip, graceful cancellation, forced termination after grace, and sibling process survival.

- [ ] **Step 3: Run and verify RED**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_worker_protocol.py tests/test_subprocess_backend.py -q`

Expected: FAIL on missing worker modules.

- [ ] **Step 4: Implement protocol and subprocess launch**

Launch `python -m agent.runtime.worker` with stdin/stdout pipes, stderr audit capture, `-u`, hidden-window flags on Windows, sanitized env, agent-home cwd, and a random one-run authentication token. Use one JSON object per line and reject messages before authenticated `hello`.

Worker broker proxies emit requests and block only on matching responses. The worker never receives provider credentials. Model and tool calls execute through supervisor brokers.

- [ ] **Step 5: Run and commit**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_worker_protocol.py tests/test_subprocess_backend.py -q`

Expected: PASS.

```powershell
git add backend/agent/runtime backend/tests/test_worker_protocol.py backend/tests/test_subprocess_backend.py
git commit -m "feat: add authenticated subprocess workers"
```

### Task 8: Supervisor, Budgets, Heartbeats, and Cancellation

**Files:**
- Create: `backend/agent/runtime/supervisor.py`
- Modify: `backend/agent/master/runtime.py`
- Test: `backend/tests/test_agent_supervisor.py`
- Test: `backend/tests/test_agent_cancellation.py`

- [ ] **Step 1: Write failing lifecycle tests**

Use deterministic fake backends and a real test subprocess. Assert lifecycle transitions `queued -> starting -> running -> completed|failed|cancelled|timed_out`, heartbeat freshness, iteration counting on model/tool operations, deadline enforcement, graceful cancellation, forced kill, descendant cancellation, and sibling continuation.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_supervisor.py tests/test_agent_cancellation.py -q`

Expected: FAIL on missing supervisor.

- [ ] **Step 3: Implement supervisor and durable task state**

Persist task trees in SQLite with run/task/parent/agent/department/state/deadline/iterations/heartbeat/exit reason. `AgentSupervisor.submit`, `cancel`, `status`, and `wait` own backend processes and brokers. A monitor checks heartbeat staleness and deadlines without blocking Vellum.

Iteration budgets count model calls and completed tool calls. Timeout zero disables wall-clock timeout but not stale-heartbeat detection.

- [ ] **Step 4: Route DelegationRuntime through supervisor**

Version-two profiles use supervisor execution. Version-one/in-process profiles retain the current path. Cache remains before submission; final result validation and storage remain after completion.

- [ ] **Step 5: Run and commit**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_supervisor.py tests/test_agent_cancellation.py tests/test_delegation_runtime.py -q`

Expected: PASS.

```powershell
git add backend/agent/runtime/supervisor.py backend/agent/master/runtime.py backend/tests/test_agent_supervisor.py backend/tests/test_agent_cancellation.py
git commit -m "feat: supervise bounded agent workers"
```

### Task 9: Parallel, Department, and Nested Orchestration

**Files:**
- Create: `backend/agent/runtime/orchestrator.py`
- Modify: `backend/agent/runtime/supervisor.py`
- Modify: `backend/agent/agents/live_dispatcher.py`
- Test: `backend/tests/test_agent_orchestration.py`

- [ ] **Step 1: Write failing orchestration tests**

Assert single-task execution, parallel concurrency cap, rejection above configured batch size, result ordering by input index, partial-failure attribution, fail-fast cancellation, department room creation, orchestrator-only child submission, depth rejection, multiplicative concurrency enforcement, and recursive cancellation.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_orchestration.py -q`

Expected: FAIL on missing orchestrator.

- [ ] **Step 3: Implement orchestrator**

Expose:

```python
await orchestrator.delegate(task)
await orchestrator.delegate_batch(tasks, fail_fast=False)
await orchestrator.delegate_department(department_id, goal, members)
await orchestrator.delegate_child(parent_task_id, task)
```

Use supervisor semaphores for global, department, parent, and profile limits. Department delegation creates a task room and posts attributed contributions. Nested requests validate parent role and `max_spawn_depth`.

- [ ] **Step 4: Preserve Vellum routing behavior**

`LiveAgentDispatcher` submits one task by default. It uses group modes only when Vellum's structured route decision explicitly requests them. Unrelated casual turns do not wait on active task trees.

- [ ] **Step 5: Run and commit**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_orchestration.py tests/test_specialist_agents.py tests/test_chat_stream_sources.py -q`

Expected: PASS.

```powershell
git add backend/agent/runtime backend/agent/agents/live_dispatcher.py backend/tests/test_agent_orchestration.py
git commit -m "feat: orchestrate parallel agent teams"
```

### Task 10: Optional Container Backend

**Files:**
- Modify: `backend/agent/runtime/backends.py`
- Create: `backend/agent/runtime/container.py`
- Test: `backend/tests/test_container_backend.py`

- [ ] **Step 1: Write failing container policy tests**

Mock the Docker command runner. Assert Docker availability detection, read-only root filesystem, explicit workspace/agent-home mounts, no host credential environment, loopback-only authenticated broker endpoint, CPU/memory/PID limits, timeout cleanup, image allowlist, fail-closed default, and explicit subprocess fallback only when configured.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_container_backend.py -q`

Expected: FAIL on missing backend.

- [ ] **Step 3: Implement Docker backend**

Construct `docker run --rm --read-only --network none --pids-limit ... --memory ... --cpus ...` with explicit mounts and no shell string interpolation. Broker networking is enabled only through a dedicated internal mode with a random token. Always remove stopped containers by exact generated ID.

- [ ] **Step 4: Run and commit**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_container_backend.py tests/test_subprocess_backend.py -q`

Expected: PASS without requiring Docker because command execution is mocked; add one opt-in integration marker for hosts with Docker.

```powershell
git add backend/agent/runtime/backends.py backend/agent/runtime/container.py backend/tests/test_container_backend.py
git commit -m "feat: add optional container agent isolation"
```

### Task 11: API, Streaming, and Required Frontend

**Files:**
- Modify: `backend/agent/api.py`
- Modify: `design/Velllum/uploads/Vellum Default Re-designed.html`
- Test: `backend/tests/test_agent_runtime_api.py`
- Test: `backend/tests/test_chat_stream_sources.py`
- Create: `frontend/ui/vellum-organizational-runtime.test.js`

- [ ] **Step 1: Write failing API and SSE tests**

Add read endpoints for departments, agents, task trees, task rooms, and worker health; add cancel/pause/resume actions with explicit confirmation where needed. Assert additive events for task queued/started/progress/message/disagreement/completed/failed/cancelled and Vellum synthesis. Existing response and legacy SSE events must remain byte-compatible.

- [ ] **Step 2: Write failing frontend contract tests**

Tests load the exact required HTML and assert it consumes organization events, renders department/agent/task hierarchy, shows individual attribution and disagreements, exposes cancel controls, keeps the main composer active while tasks run, and only renders Vellum output as the final assistant response.

- [ ] **Step 3: Run and verify RED**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_agent_runtime_api.py tests/test_chat_stream_sources.py -q
cd ..\frontend
npm test -- ui/vellum-organizational-runtime.test.js
```

Expected: backend and frontend tests fail on missing events/UI.

- [ ] **Step 4: Implement API and streaming**

Keep `/api/chat` and `/api/chat/stream` user-facing through Vellum. Add `/api/agent-runtime/*` management endpoints. Stream supervisor events through the existing response ID/thread ID envelope and attach only safe metadata.

- [ ] **Step 5: Implement the exact frontend target**

Modify only `design/Velllum/uploads/Vellum Default Re-designed.html` for the runtime UI. Add a task-tree panel showing departments, workers, statuses, progress, attribution, disagreements, and controls. Do not switch the chat into a specialist persona. Keep unrelated conversation input enabled while background tasks run.

- [ ] **Step 6: Run browser-independent contract tests and commit**

Run the commands from Step 3.

Expected: PASS.

```powershell
git add backend/agent/api.py backend/tests/test_agent_runtime_api.py backend/tests/test_chat_stream_sources.py "design/Velllum/uploads/Vellum Default Re-designed.html" frontend/ui/vellum-organizational-runtime.test.js
git commit -m "feat: expose organizational agent runtime"
```

### Task 12: End-to-End Reliability, Documentation, and Cleanup

**Files:**
- Modify: `README.md`
- Modify: `docs/AGENT_ARCHITECTURE.md`
- Modify: `docs/superpowers/specs/2026-07-04-vellum-organizational-agent-runtime-design.md` only if implementation reveals an approved clarification
- Test: all focused and repository suites

- [ ] **Step 1: Add end-to-end scenarios**

Create integration tests for:

- casual chat while SportsAgent runs
- Sports/X/YouTube isolated homes and memories
- cross-department task room with attributed disagreement
- stale-cache fallback after worker crash
- recursive cancellation
- profile identity/skill change invalidating cache
- X confirmation never replayed
- container fail-closed and subprocess fallback policy
- Vellum-only final frontend response

- [ ] **Step 2: Document operations**

Document agent-home layout, profile v2, SOUL/AGENTS/personality rules, departments, scopes, task rooms, worker backends, Docker requirements, broker policy, audits, health endpoints, cancellation, and migration/rollback.

- [ ] **Step 3: Run fresh focused verification**

Run:

```powershell
$env:PYTHONPATH='D:\Vellum\backend;D:\Vellum'
.\.venv\Scripts\python.exe -m compileall -q backend\agent
.\.venv\Scripts\python.exe -m pytest backend\tests\test_agent_profiles_v2.py backend\tests\test_agent_identity.py backend\tests\test_agent_profile_skills.py backend\tests\test_agent_execution_context.py backend\tests\test_hybrid_specialists.py backend\tests\test_organization_memory.py backend\tests\test_task_rooms.py backend\tests\test_agent_messages.py backend\tests\test_runtime_brokers.py backend\tests\test_worker_protocol.py backend\tests\test_subprocess_backend.py backend\tests\test_agent_supervisor.py backend\tests\test_agent_cancellation.py backend\tests\test_agent_orchestration.py backend\tests\test_container_backend.py backend\tests\test_agent_runtime_api.py -q
```

Expected: PASS.

- [ ] **Step 4: Run existing regression suites**

Run the current profile/cache/delegation/specialist/API/privacy/X/streaming suites and record the result separately from known unrelated repository baseline failures.

- [ ] **Step 5: Run frontend tests**

Run: `cd frontend; npm test`

Expected: PASS for the required frontend and existing UI contracts.

- [ ] **Step 6: Verify generated data is not staged**

Run: `git status --short`

Restore only test-generated tracked SQLite sidecars proven clean before testing. Never stage agent homes, private memories, task-room databases, credentials, logs, Docker state, or user Obsidian content.

- [ ] **Step 7: Commit documentation and integration tests**

```powershell
git add README.md docs/AGENT_ARCHITECTURE.md backend/tests frontend/ui
git commit -m "docs: complete organizational agent runtime"
```

## Plan Self-Review

- Identity: SOUL, AGENTS, personality overlays, scanning, truncation, stable home, and prompt order are covered by Tasks 1-2.
- Individual execution: typed contexts, skills, private state, deterministic compatibility, LLM, and hybrid opinions are covered by Task 3.
- Clean organization boundaries: private, department, organization, task-room, source, and proposal scopes plus explicit promotions are covered by Tasks 4-5.
- Isolation: tool, memory, filesystem, terminal, network, credential, and model brokers plus subprocess and container backends are covered by Tasks 6-7 and 10.
- Reliability: lifecycle, iteration/deadline budgets, heartbeat detection, crash containment, cancellation, concurrency, deterministic ordering, and nesting are covered by Tasks 8-9.
- Product behavior: Vellum remains router/final responder, casual chat remains available, and the exact required frontend is covered by Task 11.
- Compatibility and verification: current specialists, cache, X confirmation, APIs, streaming, privacy, migration, rollback, and generated-data safety are covered by Tasks 1, 3, 8, 11, and 12.
