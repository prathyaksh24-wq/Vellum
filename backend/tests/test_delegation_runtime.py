from datetime import UTC, datetime, timedelta
from pathlib import Path
import json

from langchain_core.messages import AIMessage

from agent.agents.base import SpecialistResponse
from agent.master.runtime import DelegationRuntime
from agent.memory.fts5 import FTS5Memory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
from agent.memory.resolved import ResolvedQuestionsCache
from agent.memory.specialist_cache import SpecialistResponseCache
from agent.profiles import AgentProfile, CachePolicy, MemoryPolicy, ProfileRegistry
from agent.tools.capabilities.memory_service import MemoryCapabilityService


class FakePupil:
    name = "SportsAgent"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.queries: list[str] = []

    def can_handle(self, query: str) -> bool:
        return True

    def answer(self, query: str) -> SpecialistResponse:
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("provider unavailable")
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=f"Answer for {query}",
            confidence=0.9,
        )


def build_runtime(tmp_path: Path, *, clock: list[datetime] | None = None):
    active_clock = clock or [datetime(2026, 7, 3, 10, 0, tzinfo=UTC)]
    cache = SpecialistResponseCache(tmp_path / "specialist.db", now=lambda: active_clock[0])
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=SQLiteMemoryStore(tmp_path / "memory.db"),
        memory_dir=tmp_path / "memory-files",
        specialist_cache=cache,
    )
    sports = AgentProfile(
        id="SportsAgent",
        memory=MemoryPolicy(
            read_scopes=["user_profile", "shared", "agent:SportsAgent"],
            write_scope="agent:SportsAgent",
        ),
        cache=CachePolicy(default_ttl_seconds=60, bypass_terms=[]),
    )
    profiles = ProfileRegistry(profile_dir=tmp_path / "profiles", builtins={"SportsAgent": sports})
    return DelegationRuntime(
        profile_registry=profiles,
        memory_orchestrator=orchestrator,
        now=lambda: active_clock[0],
        audit_path=tmp_path / "delegation-runs.jsonl",
    ), active_clock


def test_deterministic_run_uses_fresh_id_and_explicit_goal_only(tmp_path: Path) -> None:
    runtime, _ = build_runtime(tmp_path)
    pupil = FakePupil()

    first = runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="NBA schedule", parent_thread_id="t1")
    second = runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="NBA injuries", parent_thread_id="t1")

    assert first.run_id != second.run_id
    assert pupil.queries == ["NBA schedule", "NBA injuries"]
    assert first.profile_id == "SportsAgent"
    assert first.parent_thread_id == "t1"
    supervised = runtime.supervisor.status(first.task_id)
    assert supervised.run_id == first.run_id
    assert supervised.state == "completed"


def test_second_identical_run_uses_cache_without_calling_pupil(tmp_path: Path) -> None:
    runtime, _ = build_runtime(tmp_path)
    pupil = FakePupil()

    first = runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="Historical Arsenal titles", parent_thread_id="t1")
    second = runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="Historical Arsenal titles", parent_thread_id="t2")

    assert first.cache_status == "miss"
    assert second.cache_status == "hit"
    assert len(pupil.queries) == 1
    assert second.response == first.response


def test_identity_change_invalidates_specialist_cache(tmp_path: Path) -> None:
    runtime, _ = build_runtime(tmp_path)
    pupil = FakePupil()
    runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="Historical NBA titles", parent_thread_id="t1")
    home = runtime.agent_home_manager.ensure("SportsAgent")
    (home / "SOUL.md").write_text("A materially different sports perspective.\n", encoding="utf-8")

    second = runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="Historical NBA titles", parent_thread_id="t2")

    assert second.cache_status == "miss"
    assert len(pupil.queries) == 2


def test_live_failure_returns_stale_cached_response(tmp_path: Path) -> None:
    runtime, clock = build_runtime(tmp_path)
    runtime.delegate(profile_id="SportsAgent", pupil=FakePupil(), goal="Arsenal fixture", parent_thread_id="t1")
    clock[0] += timedelta(seconds=61)

    result = runtime.delegate(
        profile_id="SportsAgent",
        pupil=FakePupil(fail=True),
        goal="Arsenal fixture",
        parent_thread_id="t2",
    )

    assert result.cache_status == "stale_fallback"
    assert result.response.status == "stale"
    assert result.response.confidence < 0.9


def test_llm_executor_receives_only_profile_goal_context_and_memory(tmp_path: Path) -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.messages = []

        def invoke(self, messages):
            self.messages = list(messages)
            return AIMessage(content="Profile analysis")

    model = FakeModel()
    runtime, _ = build_runtime(tmp_path)
    instruction_dir = tmp_path / "profiles" / "research"
    instruction_dir.mkdir(parents=True)
    (instruction_dir / "SOUL.md").write_text("You are a focused research specialist.", encoding="utf-8")
    research = AgentProfile(
        id="ResearchAgent",
        executor="llm",
        model="openrouter/auto",
        instructions="research/SOUL.md",
        memory=MemoryPolicy(
            read_scopes=["user_profile", "shared", "agent:ResearchAgent"],
            write_scope="agent:ResearchAgent",
        ),
        cache=CachePolicy(bypass_terms=[]),
    )
    runtime.profile_registry = ProfileRegistry(
        profile_dir=tmp_path / "profiles",
        builtins={"ResearchAgent": research},
    )
    runtime.llm_factory = lambda _model=None: model

    result = runtime.delegate(
        profile_id="ResearchAgent",
        pupil=None,
        goal="Compare two storage engines",
        context="Use only the supplied benchmark notes.",
        parent_thread_id="parent-thread-with-private-history",
    )

    assert result.response.summary == "Profile analysis"
    assert len(model.messages) == 2
    assert "focused research specialist" in model.messages[0].content
    assert "Compare two storage engines" in model.messages[1].content
    assert "Use only the supplied benchmark notes" in model.messages[1].content
    assert "parent-thread-with-private-history" not in model.messages[1].content


def test_delegation_audit_is_redacted_and_records_cache_status(tmp_path: Path) -> None:
    runtime, _ = build_runtime(tmp_path)
    audit_path = tmp_path / "delegation-runs.jsonl"
    audited = DelegationRuntime(
        profile_registry=runtime.profile_registry,
        memory_orchestrator=runtime.memory_orchestrator,
        now=runtime._now,
        audit_path=audit_path,
    )
    pupil = FakePupil()

    audited.delegate(
        profile_id="SportsAgent",
        pupil=pupil,
        goal="Historical Arsenal titles",
        context="PRIVATE BENCHMARK NOTES",
        parent_thread_id="thread-1",
    )
    audited.delegate(
        profile_id="SportsAgent",
        pupil=pupil,
        goal="Historical Arsenal titles",
        context="PRIVATE BENCHMARK NOTES",
        parent_thread_id="thread-2",
    )

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert [record["cache_status"] for record in records] == ["miss", "hit"]
    assert records[0]["profile_id"] == "SportsAgent"
    assert records[0]["context_hash"]
    assert records[0]["source_count"] == 0
    assert "PRIVATE BENCHMARK NOTES" not in audit_path.read_text(encoding="utf-8")


def test_runtime_hybrid_executes_pupil_then_profile_reasoning(tmp_path: Path) -> None:
    runtime, _ = build_runtime(tmp_path)
    pupil = FakePupil()
    profile = AgentProfile(
        id="SportsAgent",
        department="sports",
        executor="hybrid",
        tools={"allow": []},
        memory=MemoryPolicy(read_scopes=["agent:SportsAgent"], write_scope="agent:SportsAgent"),
        cache=CachePolicy(bypass_terms=[]),
    )
    runtime.profile_registry = ProfileRegistry(profile_dir=tmp_path / "profiles", builtins={"SportsAgent": profile})

    class Model:
        def invoke(self, messages):
            assert "Answer for tactical review" in messages[-1].content
            return AIMessage(content="Profile-specific opinion")

    runtime.llm_factory = lambda _model=None: Model()

    result = runtime.delegate(
        profile_id="SportsAgent",
        pupil=pupil,
        goal="tactical review",
        parent_thread_id="thread-1",
    )

    assert pupil.queries == ["tactical review"]
    assert result.response.summary == "Profile-specific opinion"
