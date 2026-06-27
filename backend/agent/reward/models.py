from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RewardSignal:
    task_id: str
    pupil: str
    user_reward: float = 0.0
    master_reward: float = 0.0
    self_reward: float = 0.0


@dataclass(frozen=True)
class RewardRecord(RewardSignal):
    final_score: float = 0.0
