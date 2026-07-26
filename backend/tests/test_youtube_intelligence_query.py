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
            event_key=event,
            payload={"channel_id": channel_id, "channel_title": channel_title},
            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
            confidence=1.0,
            observed_at=observed_at,
        )
    )


def test_named_query_is_filtered_before_snapshot_limit(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db", tmp_path / "blobs")
    now = datetime(2026, 7, 23, tzinfo=UTC)
    for index in range(5):
        _watch(
            store,
            event=f"popular-{index}",
            channel_id="UC-popular",
            channel_title="Popular Channel",
            observed_at=now - timedelta(days=index + 1),
        )
    _watch(
        store,
        event="sidemen-one",
        channel_id="UC-sidemen",
        channel_title="Sidemen",
        observed_at=now - timedelta(days=20),
    )
    intelligence = YouTubeIntelligenceService(store)
    intelligence.rebuild(now=now)

    unfiltered = intelligence.snapshot(now=now, limit=1)
    filtered = intelligence.snapshot(now=now, limit=1, query="How has my interest in Sidemen changed?")

    assert unfiltered["channels"][0]["label"] == "Popular Channel"
    assert filtered["channels"][0]["label"] == "Sidemen"
