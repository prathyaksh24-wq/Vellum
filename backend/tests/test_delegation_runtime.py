from datetime import UTC, datetime, timedelta
from pathlib import Path

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
    return DelegationRuntime(profile_registry=profiles, memory_orchestrator=orchestrator, now=lambda: active_clock[0]), active_clock


def test_deterministic_run_uses_fresh_id_and_explicit_goal_only(tmp_path: Path) -> None:
    runtime, _ = build_runtime(tmp_path)
    pupil = FakePupil()

    first = runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="NBA schedule", parent_thread_id="t1")
    second = runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="NBA injuries", parent_thread_id="t1")

    assert first.run_id != second.run_id
    assert pupil.queries == ["NBA schedule", "NBA injuries"]
    assert first.profile_id == "SportsAgent"
    assert first.parent_thread_id == "t1"


def test_second_identical_run_uses_cache_without_calling_pupil(tmp_path: Path) -> None:
    runtime, _ = build_runtime(tmp_path)
    pupil = FakePupil()

    first = runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="Historical Arsenal titles", parent_thread_id="t1")
    second = runtime.delegate(profile_id="SportsAgent", pupil=pupil, goal="Historical Arsenal titles", parent_thread_id="t2")

    assert first.cache_status == "miss"
    assert second.cache_status == "hit"
    assert len(pupil.queries) == 1
    assert second.response == first.response


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
