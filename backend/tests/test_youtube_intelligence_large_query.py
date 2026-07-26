from __future__ import annotations

from datetime import UTC, datetime
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
            observed_at=datetime(2026, 7, 20, tzinfo=UTC),
        )
    )


def test_named_lookup_searches_all_subjects_and_prefers_exact_label(
    tmp_path: Path,
) -> None:
    store = KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs")
    _watch(
        store,
        event="target",
        channel_id="UC-000-target",
        channel_title="Sidemen",
    )
    _watch(
        store,
        event="similar",
        channel_id="UC-zzz-similar",
        channel_title="The Sidemen Loops",
    )
    for index in range(501):
        _watch(
            store,
            event=f"noise-{index}",
            channel_id=f"UC-z{index:04d}",
            channel_title=f"Noise Channel {index}",
        )
    intelligence = YouTubeIntelligenceService(store)
    intelligence.rebuild(now=datetime(2026, 7, 21, tzinfo=UTC))

    snapshot = intelligence.snapshot(
        now=datetime(2026, 7, 21, tzinfo=UTC),
        query="Has my interest in Sidemen changed?",
        limit=1,
    )

    assert snapshot["channels"][0]["label"] == "Sidemen"
