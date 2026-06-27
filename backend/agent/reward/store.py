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
                    pupil TEXT NOT NULL,
                    user_reward REAL NOT NULL,
                    master_reward REAL NOT NULL,
                    self_reward REAL NOT NULL,
                    final_score REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def record(self, reward: RewardRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reward_records (
                    task_id,
                    pupil,
                    user_reward,
                    master_reward,
                    self_reward,
                    final_score
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    pupil = excluded.pupil,
                    user_reward = excluded.user_reward,
                    master_reward = excluded.master_reward,
                    self_reward = excluded.self_reward,
                    final_score = excluded.final_score
                """,
                (
                    reward.task_id,
                    reward.pupil,
                    reward.user_reward,
                    reward.master_reward,
                    reward.self_reward,
                    reward.final_score,
                ),
            )

    def list_for_pupil(self, pupil: str) -> list[RewardRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, pupil, user_reward, master_reward, self_reward, final_score
                FROM reward_records
                WHERE pupil = ?
                ORDER BY created_at DESC
                """,
                (pupil,),
            ).fetchall()
        return [
            RewardRecord(
                task_id=row["task_id"],
                pupil=row["pupil"],
                user_reward=float(row["user_reward"]),
                master_reward=float(row["master_reward"]),
                self_reward=float(row["self_reward"]),
                final_score=float(row["final_score"]),
            )
            for row in rows
        ]
