import sqlite3

from agent.master.state import MasterThreadStateStore
from agent.reward.models import RewardRecord, RewardSignal
from agent.reward.scorer import RewardScorer
from agent.reward.store import RewardStore


def test_master_state_persists_active_agent_and_pending_reroute(tmp_path):
    store = MasterThreadStateStore(sessions_db=tmp_path / "sessions.db")

    store.set_active_agent("thread-1", "SportsAgent")
    store.set_pending_reroute("thread-1", "VellumAgent", "non-sports turn")

    restored = MasterThreadStateStore(sessions_db=tmp_path / "sessions.db")
    state = restored.get("thread-1")
    assert state.active_agent == "SportsAgent"
    assert state.pending_reroute_target == "VellumAgent"
    assert state.pending_reroute_reason == "non-sports turn"


def test_reward_scorer_and_store_round_trip(tmp_path):
    signal = RewardSignal(
        task_id="task-1",
        agent_id="SportsAgent",
        user_reward=0.8,
        master_reward=0.9,
        self_reward=0.6,
    )
    scored = RewardScorer().score(signal)
    store = RewardStore(db_path=tmp_path / "rewards.db")

    store.record(scored)

    assert scored.final_score == 0.805
    assert store.list_for_agent("SportsAgent")[0].task_id == "task-1"


def test_reward_store_migrates_legacy_pupil_rows(tmp_path):
    db_path = tmp_path / "rewards.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE reward_records (
                task_id TEXT PRIMARY KEY,
                pupil TEXT NOT NULL,
                user_reward REAL NOT NULL,
                master_reward REAL NOT NULL,
                self_reward REAL NOT NULL,
                final_score REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO reward_records
                (task_id, pupil, user_reward, master_reward, self_reward, final_score)
            VALUES ('legacy-task', 'SportsAgent', 0.8, 0.9, 0.6, 0.805)
            """
        )

    store = RewardStore(db_path=db_path)

    record = store.list_for_agent("SportsAgent")[0]
    assert record.task_id == "legacy-task"
    assert record.agent_id == "SportsAgent"

    store.record(
        RewardRecord(
            task_id="new-task",
            agent_id="SportsAgent",
            user_reward=0.7,
            master_reward=0.8,
            self_reward=0.6,
            final_score=0.72,
        )
    )

    assert {item.task_id for item in store.list_for_agent("SportsAgent")} == {"legacy-task", "new-task"}
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reward_records)")}
    assert "agent_id" in columns
    assert "pupil" not in columns
