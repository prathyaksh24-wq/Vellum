# Hermes Profile Delegation and Memory Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backward-compatible agent profiles, isolated delegation runs, profile-scoped cache-first retrieval, and an opt-in fresh LLM executor to Vellum's existing Master/Pupil runtime.

**Architecture:** Keep `PupilRegistry`, current specialist classes, `SpecialistResponse`, Obsidian, and the Memory Orchestrator as the stable foundation. Add a profile registry and execution policy, a specialist response cache owned by the Memory Orchestrator, and a delegation runtime called by `LiveAgentDispatcher`; deterministic profiles call existing handlers while LLM profiles receive only explicit run context and approved memory.

**Tech Stack:** Python 3.11+, Pydantic v2, PyYAML, SQLite, LangChain messages/models, FastAPI, pytest.

---

## File Structure

- Create `backend/agent/profiles/models.py`: strict profile schema and built-in safe defaults.
- Create `backend/agent/profiles/registry.py`: YAML loading, validation, instruction loading, and fallback diagnostics.
- Create `backend/agent/profiles/policy.py`: per-run context variable used to narrow shared tool access.
- Create `backend/agent/profiles/__init__.py`: public profile API.
- Create `backend/agent/memory/specialist_cache.py`: SQLite cache decisions, freshness classification, serialization, and stale lookup.
- Modify `backend/agent/memory/orchestrator.py`: own and expose the specialist cache.
- Create `backend/agent/master/runtime.py`: isolated delegation runs and deterministic/LLM executors.
- Modify `backend/agent/master/registry.py`: safe named lookup for skill routing.
- Modify `backend/agent/master/delegation.py`: delegate through the runtime while preserving the old result API.
- Modify `backend/agent/agents/live_dispatcher.py`: skill-first routing and delegation runtime integration.
- Modify `backend/agent/tools/registry.py`: enforce active profile allowlists in addition to existing agent permissions.
- Modify `backend/agent/api.py`: inject the existing Memory Orchestrator into the dispatcher and add cache/run metadata to streaming events.
- Modify `backend/pyproject.toml` and `backend/requirements.txt`: add PyYAML.
- Create `backend/tests/test_agent_profiles.py`: profile schema, loading, fallback, instructions, and tool narrowing.
- Create `backend/tests/test_specialist_cache.py`: hit/miss/stale/bypass/version/scope behavior.
- Create `backend/tests/test_delegation_runtime.py`: fresh run, deterministic and LLM execution, persistence, and stale fallback.
- Modify `backend/tests/test_specialist_agents.py`: skill route precedence and compatibility cases.
- Modify `backend/tests/test_master_pupil.py`: legacy `DelegationManager` compatibility.

### Task 1: Profile Schema and Registry

**Files:**
- Create: `backend/agent/profiles/models.py`
- Create: `backend/agent/profiles/registry.py`
- Create: `backend/agent/profiles/__init__.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_agent_profiles.py`

- [ ] **Step 1: Add PyYAML to both dependency declarations**

Add `"PyYAML>=6.0.2",` to `backend/pyproject.toml` and `PyYAML>=6.0.2` to `backend/requirements.txt` next to the other configuration dependencies.

- [ ] **Step 2: Write failing profile model and registry tests**

Create `backend/tests/test_agent_profiles.py`:

```python
from pathlib import Path

import yaml

from agent.profiles import AgentProfile, ProfileRegistry


def test_builtin_profiles_preserve_deterministic_specialists(tmp_path: Path) -> None:
    registry = ProfileRegistry(profile_dir=tmp_path)

    sports = registry.get("SportsAgent")

    assert sports.executor == "deterministic"
    assert sports.memory.write_scope == "agent:SportsAgent"
    assert sports.memory.read_scopes == ["user_profile", "shared", "agent:SportsAgent"]
    assert sports.memory.cache_first is True
    assert sports.delegation.can_delegate is False


def test_yaml_profile_overrides_builtin_without_losing_defaults(tmp_path: Path) -> None:
    (tmp_path / "SportsAgent.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "id": "SportsAgent",
                "executor": "llm",
                "description": "Focused sports analyst",
                "model": "openrouter/auto",
                "tools": {"allow": []},
                "cache": {"default_ttl_seconds": 900},
            }
        ),
        encoding="utf-8",
    )

    profile = ProfileRegistry(profile_dir=tmp_path).get("SportsAgent")

    assert profile.version == 2
    assert profile.executor == "llm"
    assert profile.model == "openrouter/auto"
    assert profile.cache.default_ttl_seconds == 900
    assert profile.cache.live_ttl_seconds == 120


def test_invalid_yaml_falls_back_to_builtin_and_records_diagnostic(tmp_path: Path) -> None:
    (tmp_path / "SportsAgent.yaml").write_text(
        "version: 1\nid: SportsAgent\nexecutor: shell\n",
        encoding="utf-8",
    )
    registry = ProfileRegistry(profile_dir=tmp_path)

    profile = registry.get("SportsAgent")

    assert profile.executor == "deterministic"
    assert registry.diagnostics()[0]["profile_id"] == "SportsAgent"
    assert registry.diagnostics()[0]["status"] == "fallback"


def test_profile_instruction_path_must_stay_inside_profile_directory(tmp_path: Path) -> None:
    profile = AgentProfile(id="ResearchAgent", executor="llm", instructions="../secret.txt")
    registry = ProfileRegistry(profile_dir=tmp_path, builtins={"ResearchAgent": profile})

    assert registry.instructions_for(profile) == ""
    assert registry.diagnostics()[0]["status"] == "blocked_instruction_path"
```

- [ ] **Step 3: Run the tests and verify the expected import failure**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_profiles.py -q`

Expected: FAIL during collection because `agent.profiles` does not exist.

- [ ] **Step 4: Implement the strict profile models and built-in defaults**

Create `backend/agent/profiles/models.py` with Pydantic models for `ToolPolicy`, `SkillPolicy`, `MemoryPolicy`, `CachePolicy`, `DelegationPolicy`, and `AgentProfile`. Use `ConfigDict(extra="forbid")`, `Literal["deterministic", "llm"]`, non-negative integer constraints, and a `model_validator` that requires `write_scope == f"agent:{id}"` unless the profile is `VellumAgent` or `MemoryAgent`. The validator must also require an empty tool allowlist for `executor="llm"` because the first LLM executor is intentionally reasoning-only.

Expose `builtin_profiles()` returning complete profiles for `SportsAgent`, `XAgent`, `YoutubeAgent`, and `MemoryAgent`. Set all executors to `deterministic`; set read scopes to `user_profile`, `shared`, and the profile's own agent scope; set `shared_writes="propose_only"`; and set `can_delegate=False`.

Use these cache defaults:

```python
CachePolicy(
    default_ttl_seconds=21600,
    live_ttl_seconds=120,
    historical_ttl_seconds=2592000,
    bypass_terms=["live", "latest", "today", "now"],
)
```

Extend XAgent's bypass terms with `post`, `publish`, `tweet`, `delete`, `remove`, `like`, `reply`, `repost`, and `retweet`. Give MemoryAgent an empty bypass list and a 30-day default TTL.

- [ ] **Step 5: Implement YAML merge, fallback diagnostics, and safe instruction loading**

Create `backend/agent/profiles/registry.py`. `ProfileRegistry.get(profile_id)` must deep-merge a YAML override onto `builtin.model_dump(mode="python")`, validate with `AgentProfile.model_validate`, and fall back to the built-in on YAML, IO, or validation errors. `try_get()` returns `None` for unknown IDs. `instructions_for()` resolves relative paths under `profile_dir`, rejects traversal using `Path.resolve().is_relative_to(profile_dir.resolve())`, and reads UTF-8 text.

Create `backend/agent/profiles/__init__.py` exporting all public models, `ProfileRegistry`, and `builtin_profiles`.

- [ ] **Step 6: Run profile tests and the current registry tests**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_profiles.py tests/test_master_pupil.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the profile foundation**

```powershell
git add backend/agent/profiles backend/tests/test_agent_profiles.py backend/pyproject.toml backend/requirements.txt
git commit -m "feat: add declarative agent profiles"
```

### Task 2: Enforce Profile Tool Narrowing

**Files:**
- Create: `backend/agent/profiles/policy.py`
- Modify: `backend/agent/profiles/__init__.py`
- Modify: `backend/agent/tools/registry.py`
- Test: `backend/tests/test_agent_profiles.py`

- [ ] **Step 1: Add failing tests for per-run tool narrowing**

Append to `backend/tests/test_agent_profiles.py`:

```python
import pytest

from agent.profiles import profile_policy
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolPermissionError, ToolRegistry


def test_active_profile_can_narrow_shared_tool_registry() -> None:
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="sports.search",
            namespace="sports",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"SportsAgent"}),
            stream_label="Searching sports",
            adapter=lambda payload: {"query": payload["query"]},
        )
    )

    with profile_policy(profile_id="SportsAgent", allowed_tools=frozenset()):
        with pytest.raises(ToolPermissionError, match="profile policy"):
            registry.invoke("sports.search", {"query": "NBA"}, agent_name="SportsAgent")


def test_no_active_profile_preserves_legacy_tool_permissions() -> None:
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="sports.search",
            namespace="sports",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"SportsAgent"}),
            stream_label="Searching sports",
            adapter=lambda payload: {"ok": True},
        )
    )

    assert registry.invoke("sports.search", {}, agent_name="SportsAgent") == {"ok": True}
```

- [ ] **Step 2: Run the two tests and verify they fail on missing policy API**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_profiles.py -q`

Expected: FAIL because `profile_policy` is not exported.

- [ ] **Step 3: Implement the context-local policy**

Create `backend/agent/profiles/policy.py` with an immutable `ActiveProfilePolicy`, a `ContextVar[ActiveProfilePolicy | None]`, a `@contextmanager profile_policy(...)` that sets and resets the variable in `finally`, and `get_active_profile_policy()`.

Modify `ToolRegistry._check_permission()` after its existing agent check:

```python
policy = get_active_profile_policy()
if policy is not None and record.name not in policy.allowed_tools:
    raise ToolPermissionError(
        f"{record.name} is not allowed by active profile policy {policy.profile_id}"
    )
```

An empty allowlist means no registry capabilities. The check supplements rather than replaces `record.allowed_agents` and confirmation enforcement.

- [ ] **Step 4: Run profile and tool registry tests**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_agent_profiles.py tests/test_tool_registry.py tests/test_shared_capability_registry.py -q`

Expected: PASS.

- [ ] **Step 5: Commit profile policy enforcement**

```powershell
git add backend/agent/profiles backend/agent/tools/registry.py backend/tests/test_agent_profiles.py
git commit -m "feat: enforce profile tool policies"
```

### Task 3: Add the Memory Orchestrator Specialist Cache

**Files:**
- Create: `backend/agent/memory/specialist_cache.py`
- Modify: `backend/agent/memory/orchestrator.py`
- Test: `backend/tests/test_specialist_cache.py`

- [ ] **Step 1: Write failing cache decision tests**

Create `backend/tests/test_specialist_cache.py` with a fixed UTC clock and tests that:

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.memory.specialist_cache import SpecialistResponseCache
from agent.profiles import CachePolicy


NOW = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)


def response(summary: str = "Arsenal play on Saturday") -> SpecialistResponse:
    return SpecialistResponse(
        agent="SportsAgent",
        status="answered",
        summary=summary,
        confidence=0.9,
        sources=[SpecialistSource(kind="web", title="Official", path_or_url="https://example.com")],
    )


def test_cache_exact_hit_round_trips_specialist_response(tmp_path: Path) -> None:
    cache = SpecialistResponseCache(tmp_path / "cache.db", now=lambda: NOW)
    policy = CachePolicy(default_ttl_seconds=3600, bypass_terms=[])
    cache.store(profile_id="SportsAgent", profile_version=1, query="When do Arsenal play?", response=response(), policy=policy)

    decision = cache.lookup(profile_id="SportsAgent", profile_version=1, query=" when do  arsenal PLAY? ", policy=policy)

    assert decision.status == "hit"
    assert decision.response == response()


def test_cache_marks_expired_entry_stale(tmp_path: Path) -> None:
    clock = [NOW]
    cache = SpecialistResponseCache(tmp_path / "cache.db", now=lambda: clock[0])
    policy = CachePolicy(default_ttl_seconds=60, bypass_terms=[])
    cache.store(profile_id="SportsAgent", profile_version=1, query="Arsenal fixture", response=response(), policy=policy)
    clock[0] += timedelta(seconds=61)

    decision = cache.lookup(profile_id="SportsAgent", profile_version=1, query="Arsenal fixture", policy=policy)

    assert decision.status == "stale"
    assert decision.response is not None


def test_live_intent_bypasses_even_when_exact_entry_exists(tmp_path: Path) -> None:
    cache = SpecialistResponseCache(tmp_path / "cache.db", now=lambda: NOW)
    policy = CachePolicy(default_ttl_seconds=3600, bypass_terms=["live", "today"])
    cache.store(profile_id="SportsAgent", profile_version=1, query="NBA score today", response=response(), policy=policy)

    decision = cache.lookup(profile_id="SportsAgent", profile_version=1, query="NBA score today", policy=policy)

    assert decision.status == "bypass"
    assert decision.reason == "live_intent:today"


def test_profile_version_change_invalidates_old_cache(tmp_path: Path) -> None:
    cache = SpecialistResponseCache(tmp_path / "cache.db", now=lambda: NOW)
    policy = CachePolicy(default_ttl_seconds=3600, bypass_terms=[])
    cache.store(profile_id="SportsAgent", profile_version=1, query="Arsenal fixture", response=response(), policy=policy)

    decision = cache.lookup(profile_id="SportsAgent", profile_version=2, query="Arsenal fixture", policy=policy)

    assert decision.status == "miss"


def test_action_requests_are_not_cacheable(tmp_path: Path) -> None:
    cache = SpecialistResponseCache(tmp_path / "cache.db", now=lambda: NOW)
    action = response().model_copy(update={"action_request": {"action": "x.post"}})

    assert cache.store(profile_id="XAgent", profile_version=1, query="post this", response=action, policy=CachePolicy()) is False
```

- [ ] **Step 2: Run cache tests and verify the missing module failure**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_specialist_cache.py -q`

Expected: FAIL during collection because `agent.memory.specialist_cache` does not exist.

- [ ] **Step 3: Implement specialist response cache storage**

Create `backend/agent/memory/specialist_cache.py` with:

- `CacheStatus = Literal["hit", "miss", "stale", "bypass"]`
- immutable `CacheDecision(status, reason, response, captured_at, expires_at)`
- SQLite table `specialist_response_cache` keyed by `(profile_id, profile_version, query_hash)`
- normalized SHA-256 query fingerprints using casefolded collapsed whitespace
- JSON serialization with `SpecialistResponse.model_dump(mode="json")`
- deserialization with `SpecialistResponse.model_validate_json()`
- `classify_freshness(query)` returning `live`, `historical`, or `default`
- TTL selection from the matching `CachePolicy` field
- exact hit, stale return, live-term bypass, and profile-version isolation
- `store()` returning `False` for errors, blocked responses, or responses with `action_request`

Corrupt JSON must be deleted and returned as a miss with reason `invalid_payload`. Use parameterized SQL only.

- [ ] **Step 4: Expose cache methods through MemoryOrchestrator**

Add a `specialist_cache: SpecialistResponseCache | None = None` dataclass field. In `__post_init__`, initialize it at `data/memory/specialist-cache.db` when not supplied. Add thin methods:

```python
def lookup_specialist_response(self, *, profile: AgentProfile, query: str) -> CacheDecision:
    return self.specialist_cache.lookup(
        profile_id=profile.id,
        profile_version=profile.version,
        query=query,
        policy=profile.cache,
    )

def store_specialist_response(self, *, profile: AgentProfile, query: str, response: SpecialistResponse) -> bool:
    return self.specialist_cache.store(
        profile_id=profile.id,
        profile_version=profile.version,
        query=query,
        response=response,
        policy=profile.cache,
    )
```

If memory settings disable memory or new-memory saving, `store_specialist_response()` returns `False`; lookup remains available when reference history is enabled.

- [ ] **Step 5: Run specialist cache and Memory Orchestrator tests**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_specialist_cache.py tests/test_memory_orchestrator.py tests/test_memory.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the specialist cache**

```powershell
git add backend/agent/memory/specialist_cache.py backend/agent/memory/orchestrator.py backend/tests/test_specialist_cache.py
git commit -m "feat: add profile-scoped specialist cache"
```

### Task 4: Implement Isolated Delegation Runs and Executors

**Files:**
- Create: `backend/agent/master/runtime.py`
- Modify: `backend/agent/master/delegation.py`
- Modify: `backend/agent/master/__init__.py`
- Test: `backend/tests/test_delegation_runtime.py`
- Test: `backend/tests/test_master_pupil.py`

- [ ] **Step 1: Write failing deterministic run and cache tests**

Create `backend/tests/test_delegation_runtime.py` using a fake pupil and real temporary cache. Assert:

```python
def test_deterministic_run_uses_fresh_id_and_explicit_goal_only(runtime, pupil) -> None:
    first = runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="NBA schedule", parent_thread_id="t1")
    second = runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="NBA injuries", parent_thread_id="t1")

    assert first.run_id != second.run_id
    assert pupil.queries == ["NBA schedule", "NBA injuries"]
    assert first.profile_id == "SportsAgent"
    assert first.parent_thread_id == "t1"


def test_second_identical_run_uses_cache_without_calling_pupil(runtime, pupil) -> None:
    first = runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="Historical Arsenal titles", parent_thread_id="t1")
    second = runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="Historical Arsenal titles", parent_thread_id="t2")

    assert first.cache_status == "miss"
    assert second.cache_status == "hit"
    assert len(pupil.queries) == 1
    assert second.response == first.response


def test_live_failure_returns_stale_cached_response(runtime_with_clock, failing_pupil) -> None:
    runtime, clock, healthy_pupil = runtime_with_clock
    runtime.delegate(profile_id="SportsAgent", pupil=healthy_pupil, goal="Arsenal fixture", parent_thread_id="t1")
    clock.advance_beyond_ttl()

    result = runtime.delegate(profile_id="SportsAgent", pupil=failing_pupil, goal="Arsenal fixture", parent_thread_id="t2")

    assert result.cache_status == "stale_fallback"
    assert result.response.status == "stale"
    assert result.response.confidence < 0.9
```

The fixture must construct `MemoryOrchestrator` with temporary SQLite/FTS/cache paths and `ProfileRegistry` with a built-in SportsAgent profile whose bypass list is empty.

- [ ] **Step 2: Run the tests and verify the runtime import failure**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_delegation_runtime.py -q`

Expected: FAIL because `agent.master.runtime` does not exist.

- [ ] **Step 3: Implement DelegationRun and deterministic execution**

Create `backend/agent/master/runtime.py` with:

- immutable `DelegationRunResult` containing `run_id`, `task_id`, `parent_thread_id`, `profile_id`, `profile_version`, `executor`, `cache_status`, `cache_reason`, `started_at`, `finished_at`, and `response`
- `DelegationRuntime(profile_registry, memory_orchestrator, llm_factory=get_routed_chat_model, now=UTC clock)`
- `delegate(profile_id, pupil, goal, parent_thread_id, context="", task_id=None)`
- UUID4 run IDs and task IDs
- cache lookup before execution when `profile.memory.cache_first` is true
- `profile_policy(...)` around deterministic execution
- successful response persistence through Memory Orchestrator
- stale fallback only when live execution raises or returns `error`
- structured error response when no stale result is available

Do not pass parent history. For deterministic profiles pass only `goal` to `pupil.answer()` to preserve the protocol. Store context in the run audit only as a SHA-256 hash, never plaintext.

- [ ] **Step 4: Write the failing opt-in LLM executor test**

Add a fake chat model whose `invoke(messages)` records messages and returns `AIMessage(content="Profile analysis")`. Configure a built-in `ResearchAgent` profile with `executor="llm"` and an instruction file. Assert the model sees exactly one system message and one human message containing goal, explicit context, and approved memory packet, but no parent transcript.

- [ ] **Step 5: Run the LLM test and verify it fails for missing executor behavior**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_delegation_runtime.py -k llm -q`

Expected: FAIL because the runtime still calls the deterministic pupil.

- [ ] **Step 6: Implement the fresh LLM executor**

For `executor="llm"`, load profile instructions, call `MemoryOrchestrator.build_memory_packet()` using the profile ID and explicit scopes, construct a new message list for every run, and invoke a newly resolved chat model without LangGraph checkpointer state:

```python
messages = [
    SystemMessage(content=instructions or f"You are {profile.id}. Return a focused specialist result."),
    HumanMessage(content=_llm_task_packet(goal=goal, context=context, memory_packet=packet)),
]
```

Normalize the model text into `SpecialistResponse(agent=profile.id, status="answered", summary=text, confidence=0.65)`. LLM profiles do not receive tools in this increment; an empty `tools.allow` is required by validation for `executor="llm"`. This prevents advertising unenforced LLM tool access while preserving deterministic agents' existing tools.

- [ ] **Step 7: Adapt DelegationManager without breaking its public result**

Allow `DelegationManager` to accept an optional runtime. When absent, preserve its current direct behavior exactly. When present, call runtime delegation and map its `SpecialistResponse` back to the existing `DelegationResult` fields. Add a compatibility test to `test_master_pupil.py` for both paths.

- [ ] **Step 8: Run delegation and Master/Pupil tests**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_delegation_runtime.py tests/test_master_pupil.py -q`

Expected: PASS.

- [ ] **Step 9: Commit isolated delegation runtime**

```powershell
git add backend/agent/master backend/tests/test_delegation_runtime.py backend/tests/test_master_pupil.py
git commit -m "feat: add isolated delegation runtime"
```

### Task 5: Integrate Skill Routing, Cache Gate, and Existing Dispatcher

**Files:**
- Modify: `backend/agent/master/registry.py`
- Modify: `backend/agent/agents/live_dispatcher.py`
- Modify: `backend/agent/api.py`
- Test: `backend/tests/test_specialist_agents.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing skill-first routing and cache reuse tests**

Add tests to `backend/tests/test_specialist_agents.py` that construct `LiveAgentDispatcher` with temporary state, a `PupilRegistry`, a fake `SkillRouteResolver`, `ProfileRegistry`, and `DelegationRuntime`:

```python
def test_live_dispatcher_prefers_valid_skill_route_over_match_order(...):
    result = dispatcher.maybe_handle("analyze this", "thread-1")
    assert result.agent_name == "ResearchAgent"
    assert result.route_source == "skill"


def test_live_dispatcher_ignores_unknown_skill_route_and_uses_matcher(...):
    result = dispatcher.maybe_handle("NBA injury report", "thread-1")
    assert result.agent_name == "SportsAgent"
    assert result.route_source == "deterministic"


def test_live_dispatcher_second_historical_query_reports_cache_hit(...):
    first = dispatcher.maybe_handle("Historical Arsenal titles", "thread-1")
    second = dispatcher.maybe_handle("Historical Arsenal titles", "thread-2")
    assert first.cache_status == "miss"
    assert second.cache_status == "hit"
```

- [ ] **Step 2: Run the new dispatcher tests and verify failures**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_specialist_agents.py -k 'skill_route or cache_hit' -q`

Expected: FAIL because dispatcher results do not expose route/cache metadata and dispatcher does not use skill routing.

- [ ] **Step 3: Add safe registry lookup**

Add `PupilRegistry.try_get(name) -> SpecialistAgent | None` and use it for skill routes. Do not change `get()` so existing callers still receive `KeyError` for invalid direct access.

- [ ] **Step 4: Integrate ProfileRegistry and DelegationRuntime into LiveAgentDispatcher**

Add optional constructor dependencies for `skill_route_resolver`, `profile_registry`, and `delegation_runtime`. Preserve current defaults. Selection order is pending action, valid skill route, then `registry.match()`.

Replace only the normal `matched_pupil.answer(message)` call with:

```python
run = self.delegation_runtime.delegate(
    profile_id=matched_pupil.name,
    pupil=matched_pupil,
    goal=message,
    parent_thread_id=thread_id,
)
response = run.response
```

Keep pending confirmed action execution outside cache/delegation so writes are never replayed. Extend `LiveAgentResult` with defaulted optional `confidence`, `run_id`, `cache_status`, `cache_reason`, and `route_source` fields. Populate them from the run without changing existing fields.

- [ ] **Step 5: Inject the existing Memory Orchestrator in API startup**

Construct `_live_dispatcher` only after `_memory_orchestrator`, passing a `DelegationRuntime(ProfileRegistry(), _memory_orchestrator)`. Do not create a second production Memory Orchestrator or specialist cache.

Add `run_id`, `cache_status`, and `cache_reason` to subagent streaming item metadata. Do not change required response fields or legacy SSE names.

- [ ] **Step 6: Correct specialist memory-candidate ownership**

In `_background_learn`, change `extract_memory_candidates(..., agent_name="VellumAgent")` to `agent_name=agent_name`. This preserves main-agent behavior because the parameter defaults to `VellumAgent`, while specialist turns now write proposals to their declared scope. Add an API-level test asserting SportsAgent candidates use `agent:SportsAgent`.

- [ ] **Step 7: Run dispatcher, API, streaming, and X confirmation regressions**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_specialist_agents.py tests/test_api.py tests/test_chat_stream_sources.py tests/test_x_tool.py -q`

Expected: PASS, including existing pending confirmation and X passthrough tests.

- [ ] **Step 8: Commit runtime integration**

```powershell
git add backend/agent/master/registry.py backend/agent/agents/live_dispatcher.py backend/agent/api.py backend/tests/test_specialist_agents.py backend/tests/test_api.py
git commit -m "feat: route specialists through profile runtime"
```

### Task 6: Add Run Audit Persistence and Status Diagnostics

**Files:**
- Modify: `backend/agent/master/runtime.py`
- Modify: `backend/agent/api.py`
- Test: `backend/tests/test_delegation_runtime.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing audit persistence tests**

Add a temporary `audit_path` to the runtime fixture. After a miss then hit, read JSONL records and assert each contains run/task/thread/profile/version/executor/route-independent cache status/start/finish/status, context hash, tools/sources counts, and no plaintext explicit context.

Add an API status test asserting profile diagnostics expose profile ID, version, executor, cache policy, and fallback status without instructions or secrets.

- [ ] **Step 2: Run audit/status tests and verify missing behavior**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_delegation_runtime.py tests/test_api.py -k 'audit or profile_status' -q`

Expected: FAIL because no audit file or profile status endpoint exists.

- [ ] **Step 3: Persist redacted run audit records**

Append one UTF-8 JSON object per completed run to `data/memory/delegation-runs.jsonl` by default. Use a process lock, ensure the parent directory exists, and include hashes/counts instead of raw context, responses, or source content. Audit write failures must be logged and must not affect the returned response.

- [ ] **Step 4: Expose read-only profile status**

Add `GET /agent-profiles` returning public profile summaries and registry diagnostics. Public summaries include `id`, `version`, `description`, `executor`, allowed tool names, memory scopes, cache TTLs, and delegation limits. They exclude instruction contents, environment values, API keys, model credentials, and private memory.

- [ ] **Step 5: Run audit, API, and privacy tests**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_delegation_runtime.py tests/test_api.py tests/test_privacy.py -q`

Expected: PASS.

- [ ] **Step 6: Commit observability**

```powershell
git add backend/agent/master/runtime.py backend/agent/api.py backend/tests/test_delegation_runtime.py backend/tests/test_api.py
git commit -m "feat: audit profile delegation runs"
```

### Task 7: Full Verification and Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/AGENT_ARCHITECTURE.md`
- Test: all backend tests

- [ ] **Step 1: Document profile creation and cache behavior**

Add concise sections covering:

- profile directory and safe fallback behavior
- deterministic versus LLM executors
- explicit-context isolation
- tool and memory scope narrowing
- cache statuses and freshness classes
- live-intent bypass
- read-only profile status endpoint
- example YAML for adding a future ResearchAgent

State explicitly that profiles are policy boundaries, not operating-system sandboxes.

- [ ] **Step 2: Run formatting/static sanity checks**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m compileall agent
..\.venv\Scripts\python.exe -m pytest tests/test_agent_profiles.py tests/test_specialist_cache.py tests/test_delegation_runtime.py -q
```

Expected: compilation succeeds and focused tests pass.

- [ ] **Step 3: Run the full backend test suite**

Run: `cd backend; ..\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass with no new warnings attributable to this feature.

- [ ] **Step 4: Verify the working tree contains no accidental runtime data**

Run: `git status --short`

Expected: only intended source/docs/test changes are present. Do not stage `data/llm-routing/*.db-shm`, `data/llm-routing/*.db-wal`, memory databases, logs, cache files, or user Obsidian content.

- [ ] **Step 5: Commit documentation and final verification changes**

```powershell
git add README.md docs/AGENT_ARCHITECTURE.md
git commit -m "docs: explain agent profiles and cache-first delegation"
```

## Plan Self-Review

- Spec coverage: profiles, deterministic compatibility, opt-in fresh LLM calls, skill-first routing, explicit context, tool narrowing, scoped memory, cache freshness, stale fallback, audit records, status diagnostics, and X confirmation compatibility are assigned to concrete tasks.
- Scope: all tasks serve one cohesive runtime extension; no UI redesign, process isolation, recursive delegation, or credential migration is included.
- Type consistency: `AgentProfile`, `CachePolicy`, `CacheDecision`, `DelegationRunResult`, `ProfileRegistry`, and `DelegationRuntime` names and call signatures are consistent across tasks.
- Safety: live writes bypass cache, profile policies only narrow permissions, invalid profiles fall back safely, and existing runtime databases are excluded from commits.
