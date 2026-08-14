from datetime import UTC, datetime, timedelta
from pathlib import Path
import json

from langchain_core.messages import AIMessage, HumanMessage

from agent.agents.base import SpecialistResponse
from agent.master.runtime import DelegationRequest, DelegationRuntime
from agent.llm.routing.chat_model import RoutedChatModel
from agent.memory.fts5 import FTS5Memory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
from agent.memory.resolved import ResolvedQuestionsCache
from agent.memory.specialist_cache import SpecialistResponseCache
from agent.profiles import AgentCatalog, AgentProfile, CachePolicy, DelegationPolicy, MemoryPolicy
from agent.tools.capabilities.memory_service import MemoryCapabilityService


class FakeAgent:
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
    profiles = AgentCatalog(profile_dir=tmp_path / "profiles", builtins={"SportsAgent": sports})
    return DelegationRuntime(
        agent_catalog=profiles,
        memory_orchestrator=orchestrator,
        now=lambda: active_clock[0],
        audit_path=tmp_path / "delegation-runs.jsonl",
    ), active_clock


def test_delegation_request_resolves_executor_from_agent_catalog(tmp_path: Path) -> None:
    existing, clock = build_runtime(tmp_path)
    agent = FakeAgent()
    profile = existing.agent_catalog.get("SportsAgent")
    catalog = AgentCatalog(
        profile_dir=tmp_path / "profiles",
        builtins={"SportsAgent": profile},
        executors={"SportsAgent": agent},
    )
    runtime = DelegationRuntime(
        agent_catalog=catalog,
        memory_orchestrator=existing.memory_orchestrator,
        now=lambda: clock[0],
        audit_path=tmp_path / "delegation-runs.jsonl",
    )

    result = runtime.delegate(
        DelegationRequest(
            agent_id="SportsAgent",
            task="NBA schedule",
            parent_thread_id="thread-1",
        )
    )

    assert result.profile_id == "SportsAgent"
    assert result.parent_thread_id == "thread-1"
    assert result.response.summary == "Answer for NBA schedule"
    assert agent.queries == ["NBA schedule"]


def test_deterministic_run_uses_fresh_id_and_explicit_goal_only(tmp_path: Path) -> None:
    runtime, _ = build_runtime(tmp_path)
    agent = FakeAgent()
    runtime.agent_catalog.register_executor("SportsAgent", agent)

    first = runtime.delegate(DelegationRequest(agent_id="SportsAgent", task="NBA schedule", parent_thread_id="t1"))
    second = runtime.delegate(DelegationRequest(agent_id="SportsAgent", task="NBA injuries", parent_thread_id="t1"))

    assert first.run_id != second.run_id
    assert agent.queries == ["NBA schedule", "NBA injuries"]
    assert first.profile_id == "SportsAgent"
    assert first.parent_thread_id == "t1"


def test_profile_can_refuse_delegated_work(tmp_path: Path) -> None:
    runtime, _ = build_runtime(tmp_path)
    agent = FakeAgent()
    profile = runtime.agent_catalog.get("SportsAgent").model_copy(
        update={"delegation": DelegationPolicy(can_receive=False)}
    )
    runtime.agent_catalog = AgentCatalog(
        profile_dir=tmp_path / "profiles",
        builtins={"SportsAgent": profile},
        executors={"SportsAgent": agent},
    )

    result = runtime.delegate(
        DelegationRequest(
            agent_id="SportsAgent",
            task="NBA schedule",
            parent_thread_id="t1",
        )
    )

    assert result.response.status == "blocked"
    assert result.cache_reason == "delegation_policy"
    assert agent.queries == []


def test_profile_rejects_delegation_beyond_max_depth(tmp_path: Path) -> None:
    runtime, _ = build_runtime(tmp_path)
    agent = FakeAgent()
    profile = runtime.agent_catalog.get("SportsAgent").model_copy(
        update={"delegation": DelegationPolicy(max_depth=1)}
    )
    runtime.agent_catalog = AgentCatalog(
        profile_dir=tmp_path / "profiles",
        builtins={"SportsAgent": profile},
        executors={"SportsAgent": agent},
    )

    result = runtime.delegate(
        DelegationRequest(
            agent_id="SportsAgent",
            task="NBA schedule",
            parent_thread_id="t1",
            depth=2,
        )
    )

    assert result.response.status == "blocked"
    assert result.cache_reason == "delegation_policy"
    assert agent.queries == []


def test_second_identical_run_uses_cache_without_calling_agent(tmp_path: Path) -> None:
    runtime, _ = build_runtime(tmp_path)
    agent = FakeAgent()
    runtime.agent_catalog.register_executor("SportsAgent", agent)

    first = runtime.delegate(
        DelegationRequest(agent_id="SportsAgent", task="Historical Arsenal titles", parent_thread_id="t1")
    )
    second = runtime.delegate(
        DelegationRequest(agent_id="SportsAgent", task="Historical Arsenal titles", parent_thread_id="t2")
    )

    assert first.cache_status == "miss"
    assert second.cache_status == "hit"
    assert len(agent.queries) == 1
    assert second.response == first.response


def test_live_failure_returns_stale_cached_response(tmp_path: Path) -> None:
    runtime, clock = build_runtime(tmp_path)
    runtime.agent_catalog.register_executor("SportsAgent", FakeAgent())
    runtime.delegate(DelegationRequest(agent_id="SportsAgent", task="Arsenal fixture", parent_thread_id="t1"))
    clock[0] += timedelta(seconds=61)
    runtime.agent_catalog.register_executor("SportsAgent", FakeAgent(fail=True))

    result = runtime.delegate(
        DelegationRequest(agent_id="SportsAgent", task="Arsenal fixture", parent_thread_id="t2")
    )

    assert result.cache_status == "stale_fallback"
    assert result.response.status == "stale"
    assert result.response.confidence < 0.9


def test_llm_executor_receives_only_profile_goal_context_and_memory(tmp_path: Path) -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.messages = []
            self.config = None

        def invoke(self, messages, config=None):
            self.messages = list(messages)
            self.config = config
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
        instructions={"files": ["research/SOUL.md"]},
        memory=MemoryPolicy(
            read_scopes=["user_profile", "shared", "agent:ResearchAgent"],
            write_scope="agent:ResearchAgent",
        ),
        cache=CachePolicy(bypass_terms=[]),
    )
    runtime.agent_catalog = AgentCatalog(
        profile_dir=tmp_path / "profiles",
        builtins={"ResearchAgent": research},
    )
    runtime.llm_factory = lambda _model=None: model

    result = runtime.delegate(
        DelegationRequest(
            agent_id="ResearchAgent",
            task="Compare two storage engines",
            context="Use only the supplied benchmark notes.",
            parent_thread_id="parent-thread-with-private-history",
        )
    )

    assert result.response.summary == "Profile analysis"
    assert len(model.messages) == 2
    assert "focused research specialist" in model.messages[0].content
    assert "Compare two storage engines" in model.messages[1].content
    assert "Use only the supplied benchmark notes" in model.messages[1].content
    assert "parent-thread-with-private-history" not in model.messages[1].content
    assert model.config == {"configurable": {"thread_id": "parent-thread-with-private-history"}}


def test_synchronous_routed_model_forwards_thread_id_to_engine() -> None:
    class FakeEngine:
        def __init__(self) -> None:
            self.kwargs = None

        async def ainvoke(self, **kwargs):
            self.kwargs = kwargs
            return AIMessage(content="Routed result")

    engine = FakeEngine()
    model = RoutedChatModel(
        engine=engine,
        primary_model_resolver=lambda: "openrouter/auto",
    )

    result = model.invoke(
        [HumanMessage(content="Research this")],
        config={"configurable": {"thread_id": "delegated-thread"}},
    )

    assert result.content == "Routed result"
    assert engine.kwargs["thread_id"] == "delegated-thread"


def test_cached_response_must_match_selected_agent(tmp_path: Path) -> None:
    runtime, _ = build_runtime(tmp_path)
    agent = FakeAgent()
    runtime.agent_catalog.register_executor("SportsAgent", agent)
    profile = runtime.agent_catalog.get("SportsAgent")
    runtime.memory_orchestrator.specialist_cache.store(
        profile_id=profile.id,
        profile_version=profile.version,
        query="Historical Arsenal titles",
        response=SpecialistResponse(
            agent="XAgent",
            status="answered",
            summary="Wrong agent cache entry",
            confidence=0.9,
        ),
        policy=profile.cache,
    )

    result = runtime.delegate(
        DelegationRequest(
            agent_id="SportsAgent",
            task="Historical Arsenal titles",
            parent_thread_id="thread-1",
        )
    )

    assert result.response.agent == "SportsAgent"
    assert result.response.summary != "Wrong agent cache entry"
    assert agent.queries == ["Historical Arsenal titles"]


def test_delegation_audit_is_redacted_and_records_cache_status(tmp_path: Path) -> None:
    runtime, _ = build_runtime(tmp_path)
    audit_path = tmp_path / "delegation-runs.jsonl"
    audited = DelegationRuntime(
        agent_catalog=runtime.agent_catalog,
        memory_orchestrator=runtime.memory_orchestrator,
        now=runtime._now,
        audit_path=audit_path,
    )
    agent = FakeAgent()
    audited.agent_catalog.register_executor("SportsAgent", agent)

    audited.delegate(
        DelegationRequest(
            agent_id="SportsAgent",
            task="Historical Arsenal titles",
            context="PRIVATE BENCHMARK NOTES",
            parent_thread_id="thread-1",
        )
    )
    audited.delegate(
        DelegationRequest(
            agent_id="SportsAgent",
            task="Historical Arsenal titles",
            context="PRIVATE BENCHMARK NOTES",
            parent_thread_id="thread-2",
        )
    )

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert [record["cache_status"] for record in records] == ["bypass", "bypass"]
    assert [record["cache_reason"] for record in records] == ["explicit_context", "explicit_context"]
    assert records[0]["profile_id"] == "SportsAgent"
    assert records[0]["context_hash"]
    assert records[0]["source_count"] == 0
    assert "PRIVATE BENCHMARK NOTES" not in audit_path.read_text(encoding="utf-8")
