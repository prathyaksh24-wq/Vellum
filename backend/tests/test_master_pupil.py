from pathlib import Path

from agent.agents.base import MemoryProposal, SpecialistResponse
from agent.master.delegation import DelegationManager
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
    assert hasattr(registry.get("YoutubeAgent"), "youtube_service")
    assert hasattr(registry.get("MemoryAgent"), "memory_service")


def test_pupil_registry_prioritizes_explicit_source_agents_over_sports(tmp_path):
    registry = PupilRegistry.default(vault_root=tmp_path)

    assert registry.match("What did the NBA post on X?").name == "XAgent"
    assert registry.match("Give me NBA YouTube videos").name == "YoutubeAgent"
    assert registry.match("NBA Finals injury report").name == "SportsAgent"


def test_pupil_registry_does_not_route_generic_context_to_memory(tmp_path):
    registry = PupilRegistry.default(vault_root=tmp_path)

    assert registry.match("Give me context on NBA Finals injury report").name == "SportsAgent"
    assert registry.match("Can you give me context for this Python error?") is None


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
