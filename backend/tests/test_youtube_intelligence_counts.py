from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent.knowledge.models import ObservationActor, ObservationInput, Sensitivity
from agent.knowledge.store import KnowledgeStore
from agent.plugins.youtube_intelligence import YouTubeIntelligenceService


def _watch(store: KnowledgeStore, *, event: str, channel: str) -> None:
    store.record_observation(
        ObservationInput(
            origin="youtube_takeout",
            action="youtube.watch",
            actor=ObservationActor.IMPORTED,
            trigger="google_takeout",
            event_key=event,
            payload={
                "video_id": event,
                "channel_id": f"UC-{channel.casefold()}",
                "channel_title": channel,
            },
            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
            confidence=1.0,
            observed_at=datetime(2026, 7, 20, tzinfo=UTC),
        )
    )


def test_snapshot_distinguishes_total_and_returned_counts(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs")
    _watch(store, event="one", channel="One")
    _watch(store, event="two", channel="Two")
    intelligence = YouTubeIntelligenceService(store)
    intelligence.rebuild(now=datetime(2026, 7, 21, tzinfo=UTC))

    snapshot = intelligence.snapshot(
        now=datetime(2026, 7, 21, tzinfo=UTC),
        limit=1,
    )

    assert snapshot["counts"] == {"channels": 2, "search_themes": 0}
    assert snapshot["returned_counts"] == {"channels": 1, "search_themes": 0}
