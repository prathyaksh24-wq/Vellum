from __future__ import annotations

from agent.reward.models import RewardRecord, RewardSignal


class RewardScorer:
    def score(self, signal: RewardSignal) -> RewardRecord:
        final_score = (
            signal.user_reward * 0.50
            + signal.master_reward * 0.35
            + signal.self_reward * 0.15
        )
        return RewardRecord(
            task_id=signal.task_id,
            pupil=signal.pupil,
            user_reward=signal.user_reward,
            master_reward=signal.master_reward,
            self_reward=signal.self_reward,
            final_score=round(final_score, 3),
        )
