from __future__ import annotations

from pathlib import Path
import sqlite3

from agent.reward.models import RewardRecord


class RewardStore:
    def __init__(self, db_path: Path = Path("data/memory/rewards.db")) -> None:
        self.db_path = Path(db_path)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reward_records (
                    task_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    user_reward REAL NOT NULL,
                    master_reward REAL NOT NULL,
                    self_reward REAL NOT NULL,
                    final_score REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(reward_records)")}
            if "pupil" in columns:
                agent_expression = "COALESCE(NULLIF(agent_id, ''), pupil)" if "agent_id" in columns else "pupil"
                conn.execute("DROP TABLE IF EXISTS reward_records_agent_id_migration")
                conn.execute(
                    """
                    CREATE TABLE reward_records_agent_id_migration (
                        task_id TEXT PRIMARY KEY,
                        agent_id TEXT NOT NULL,
                        user_reward REAL NOT NULL,
                        master_reward REAL NOT NULL,
                        self_reward REAL NOT NULL,
                        final_score REAL NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    f"""
                    INSERT INTO reward_records_agent_id_migration (
                        task_id,
                        agent_id,
                        user_reward,
                        master_reward,
                        self_reward,
                        final_score,
                        created_at
                    )
                    SELECT
                        task_id,
                        {agent_expression},
                        user_reward,
                        master_reward,
                        self_reward,
                        final_score,
                        created_at
                    FROM reward_records
                    """
                )
                conn.execute("DROP TABLE reward_records")
                conn.execute("ALTER TABLE reward_records_agent_id_migration RENAME TO reward_records")
            elif "agent_id" not in columns:
                raise RuntimeError("reward_records is missing an agent identity column")

    def record(self, reward: RewardRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reward_records (
                    task_id,
                    agent_id,
                    user_reward,
                    master_reward,
                    self_reward,
                    final_score
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    agent_id = excluded.agent_id,
                    user_reward = excluded.user_reward,
                    master_reward = excluded.master_reward,
                    self_reward = excluded.self_reward,
                    final_score = excluded.final_score
                """,
                (
                    reward.task_id,
                    reward.agent_id,
                    reward.user_reward,
                    reward.master_reward,
                    reward.self_reward,
                    reward.final_score,
                ),
            )

    def list_for_agent(self, agent_id: str) -> list[RewardRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, agent_id, user_reward, master_reward, self_reward, final_score
                FROM reward_records
                WHERE agent_id = ?
                ORDER BY created_at DESC
                """,
                (agent_id,),
            ).fetchall()
        return [
            RewardRecord(
                task_id=row["task_id"],
                agent_id=row["agent_id"],
                user_reward=float(row["user_reward"]),
                master_reward=float(row["master_reward"]),
                self_reward=float(row["self_reward"]),
                final_score=float(row["final_score"]),
            )
            for row in rows
        ]
