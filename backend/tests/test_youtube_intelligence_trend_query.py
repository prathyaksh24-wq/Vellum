from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent.knowledge.models import ObservationActor, ObservationInput, Sensitivity
from agent.knowledge.store import KnowledgeStore
from agent.plugins.youtube_intelligence import YouTubeIntelligenceService


def _watch(
    store: KnowledgeStore,
    *,
    event: str,
    channel_id: str,
    channel_title: str,
    observed_at: datetime,
) -> None:
    store.record_observation(
        ObservationInput(
            origin="youtube_takeout",
            action="youtube.watch",
            actor=ObservationActor.IMPORTED,
            trigger="google_takeout",
            event_key=event,
            payload={
                "video_id": event,
                "channel_id": channel_id,
                "channel_title": channel_title,
            },
            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
            confidence=1.0,
            observed_at=observed_at,
        )
    )


def test_falling_query_ranks_falling_preferences_before_response_limit(
    tmp_path: Path,
) -> None:
    store = KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs")
    now = datetime(2026, 7, 23, tzinfo=UTC)
    for index in range(10):
        _watch(
            store,
            event=f"old-{index}",
            channel_id="UC-falling",
            channel_title="Falling Channel",
            observed_at=now - timedelta(days=40 + index * 5),
        )
    for index in range(10):
        _watch(
            store,
            event=f"recent-{index}",
            channel_id="UC-active",
            channel_title="Active Channel",
            observed_at=now - timedelta(days=index + 1),
        )
    intelligence = YouTubeIntelligenceService(store)
    intelligence.rebuild(now=now)

    snapshot = intelligence.snapshot(
        now=now,
        query="Which YouTube channels am I losing interest in?",
        limit=1,
    )

    assert snapshot["channels"][0]["label"] == "Falling Channel"
    assert snapshot["channels"][0]["trend"] == "falling"
