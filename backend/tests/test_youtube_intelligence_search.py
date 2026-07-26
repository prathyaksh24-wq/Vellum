from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent.knowledge.models import ObservationActor, ObservationInput, Sensitivity
from agent.knowledge.store import KnowledgeStore
from agent.plugins.youtube_intelligence import YouTubeIntelligenceService


def test_rebuild_groups_repeated_searches_as_local_search_themes(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db", tmp_path / "blobs")
    now = datetime(2026, 7, 23, tzinfo=UTC)
    queries = ["Arsenal tactics", "arsenal   tactics", "ARSENAL TACTICS", "pasta recipe"]
    for index, query in enumerate(queries):
        store.record_observation(
            ObservationInput(
                origin="youtube_takeout",
                action="youtube.search",
                actor=ObservationActor.IMPORTED,
                trigger="google_takeout",
                event_key=f"search-{index}",
                payload={"query": query},
                sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                confidence=1.0,
                observed_at=now - timedelta(days=index + 1),
            )
        )

    intelligence = YouTubeIntelligenceService(store)
    result = intelligence.rebuild(now=now)
    snapshot = intelligence.snapshot(now=now)

    assert result["observations_scanned"] == 4
    assert result["signals_created"] == 4
    assert result["subjects_recomputed"] == 2
    assert snapshot["local_only"] is True
    assert snapshot["search_themes"][0]["label"] == "Arsenal tactics"
    assert snapshot["search_themes"][0]["evidence_count"] == 3
    assert snapshot["search_themes"][0]["confidence"] > snapshot["search_themes"][1]["confidence"]
