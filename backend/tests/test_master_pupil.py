from pathlib import Path

from agent.agents.base import MemoryProposal, SpecialistResponse
from agent.master.delegation import DelegationManager
from agent.master.runtime import DelegationRunResult
from agent.master.registry import PupilRegistry
from agent.master.state import MasterThreadStateStore
from agent.reward.models import RewardSignal
from agent.reward.scorer import RewardScorer
from agent.reward.store import RewardStore


def test_pupil_registry_exposes_default_pupils(tmp_path):
    registry = PupilRegistry.default(vault_root=tmp_path)

    assert {"SportsAgent", "XAgent", "YoutubeAgent", "MemoryAgent"} <= set(registry.names())
    assert registry.get("SportsAgent").can_handle("NBA update")
    assert hasattr(registry.get("XAgent"), "x_service")


def test_default_pupil_registry_shares_one_tool_registry(tmp_path):
    registry = PupilRegistry.default(vault_root=tmp_path)

    x_registry = registry.get("XAgent").tool_registry
    youtube_registry = registry.get("YoutubeAgent").tool_registry
    memory_registry = registry.get("MemoryAgent").tool_registry

    assert x_registry is not None
    assert x_registry is youtube_registry
    assert x_registry is memory_registry
    assert "youtube.search_videos" in x_registry.names()


def test_pupil_registry_prioritizes_explicit_source_agents_over_sports(tmp_path):
    registry = PupilRegistry.default(vault_root=tmp_path)

    assert registry.match("What did the NBA post on X?").name == "XAgent"
    assert registry.match("Give me NBA YouTube videos").name == "YoutubeAgent"
    assert registry.match("NBA Finals injury report").name == "SportsAgent"


def test_master_state_persists_active_agent_and_pending_reroute(tmp_path):
    store = MasterThreadStateStore(sessions_db=tmp_path / "sessions.db")

    store.set_active_agent("thread-1", "SportsAgent")
    store.set_pending_reroute("thread-1", "VellumAgent", "non-sports turn")

    restored = MasterThreadStateStore(sessions_db=tmp_path / "sessions.db")
    state = restored.get("thread-1")
    assert state.active_agent == "SportsAgent"
    assert state.pending_reroute_target == "VellumAgent"
    assert state.pending_reroute_reason == "non-sports turn"


def test_delegation_manager_normalizes_pupil_response_and_memory_proposals(tmp_path):
    class FakePupil:
        name = "MemoryAgent"

        def can_handle(self, query):
            return True

        def answer(self, query):
            return SpecialistResponse(
                agent=self.name,
                status="answered",
                summary="Remembered as proposal",
                confidence=0.9,
                memory_proposals=[
                    MemoryProposal(scope="memory", claim="User likes concise answers.", evidence=query, confidence=0.85)
                ],
            )

    manager = DelegationManager(PupilRegistry({"MemoryAgent": FakePupil()}))

    result = manager.delegate("MemoryAgent", "remember concise answers", task_id="task-1")

    assert result.task_id == "task-1"
    assert result.pupil == "MemoryAgent"
    assert result.status == "answered"
    assert result.answer == "Remembered as proposal"
    assert result.memory_proposals[0].claim == "User likes concise answers."


def test_delegation_manager_contains_pupil_failures(tmp_path):
    class FailingPupil:
        name = "FailingAgent"

        def can_handle(self, query):
            return True

        def answer(self, query):
            raise RuntimeError("backend unavailable")

    manager = DelegationManager(PupilRegistry({"FailingAgent": FailingPupil()}))

    result = manager.delegate("FailingAgent", "handle this", task_id="task-err")

    assert result.task_id == "task-err"
    assert result.pupil == "FailingAgent"
    assert result.status == "error"
    assert "could not complete" in result.answer
    assert result.confidence == 0.0
    assert result.sources == []
    assert result.memory_proposals == []


def test_delegation_manager_can_use_profile_runtime_without_changing_result_contract(tmp_path):
    class FakePupil:
        name = "MemoryAgent"

        def can_handle(self, query):
            return True

        def answer(self, query):
            raise AssertionError("runtime should own execution")

    class FakeRuntime:
        def delegate(self, **kwargs):
            assert kwargs["profile_id"] == "MemoryAgent"
            assert kwargs["goal"] == "remember this"
            return DelegationRunResult(
                run_id="run-1",
                task_id="task-1",
                parent_thread_id="thread-1",
                profile_id="MemoryAgent",
                profile_version=1,
                executor="deterministic",
                cache_status="miss",
                cache_reason="not_found",
                started_at="2026-07-03T00:00:00+00:00",
                finished_at="2026-07-03T00:00:01+00:00",
                response=SpecialistResponse(
                    agent="MemoryAgent",
                    status="answered",
                    summary="Remembered through runtime",
                    confidence=0.88,
                ),
            )

    manager = DelegationManager(PupilRegistry({"MemoryAgent": FakePupil()}), runtime=FakeRuntime())

    result = manager.delegate("MemoryAgent", "remember this", task_id="task-1", parent_thread_id="thread-1")

    assert result.answer == "Remembered through runtime"
    assert result.status == "answered"
    assert result.confidence == 0.88


def test_reward_scorer_and_store_round_trip(tmp_path):
    signal = RewardSignal(
        task_id="task-1",
        pupil="SportsAgent",
        user_reward=0.8,
        master_reward=0.9,
        self_reward=0.6,
    )
    scored = RewardScorer().score(signal)
    store = RewardStore(db_path=tmp_path / "rewards.db")

    store.record(scored)

    assert scored.final_score == 0.805
    assert store.list_for_pupil("SportsAgent")[0].task_id == "task-1"
