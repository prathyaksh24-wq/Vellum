from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent.knowledge.models import ObservationActor, ObservationInput, Sensitivity
from agent.knowledge.store import KnowledgeStore
from agent.plugins.youtube_intelligence import YouTubeIntelligenceService


def _store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(tmp_path / "knowledge.db", tmp_path / "blobs")


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
                "title": f"Video {event}",
                "channel_id": channel_id,
                "channel_title": channel_title,
            },
            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
            confidence=1.0,
            observed_at=observed_at,
        )
    )


def test_rebuild_creates_idempotent_channel_interest_snapshot(tmp_path: Path) -> None:
    store = _store(tmp_path)
    now = datetime(2026, 7, 23, tzinfo=UTC)
    _watch(
        store,
        event="watch-1",
        channel_id="UC-sidemen",
        channel_title="Sidemen",
        observed_at=now - timedelta(days=7),
    )
    _watch(
        store,
        event="watch-2",
        channel_id="UC-sidemen",
        channel_title="Sidemen",
        observed_at=now - timedelta(days=3),
    )

    intelligence = YouTubeIntelligenceService(store)
    first = intelligence.rebuild(now=now)
    second = intelligence.rebuild(now=now)
    snapshot = intelligence.snapshot(now=now)

    assert first == {
        "observations_scanned": 2,
        "signals_created": 2,
        "signals_existing": 0,
        "signals_removed": 0,
        "subjects_recomputed": 1,
        "identity": {
            "records_scanned": 2,
            "entities_created": 1,
            "entities_existing": 0,
            "aliases_created": 1,
            "aliases_existing": 0,
        },
    }
    assert second["signals_created"] == 0
    assert second["signals_existing"] == 2
    assert second["identity"] == {
        "records_scanned": 2,
        "entities_created": 0,
        "entities_existing": 1,
        "aliases_created": 0,
        "aliases_existing": 1,
    }
    assert snapshot["local_only"] is True
    assert snapshot["channels"][0]["subject_key"] == "youtube:channel:UC-sidemen"
    assert snapshot["channels"][0]["label"] == "Sidemen"
    assert snapshot["channels"][0]["evidence_count"] == 2
    assert snapshot["channels"][0]["latest_observation_at"] == (now - timedelta(days=3)).isoformat()


def test_snapshot_detects_declining_watch_frequency_without_claiming_completion(tmp_path: Path) -> None:
    store = _store(tmp_path)
    now = datetime(2026, 7, 23, tzinfo=UTC)

    for index, days_ago in enumerate(range(45, 105, 5)):
        _watch(
            store,
            event=f"historical-{index}",
            channel_id="UC-sidemen",
            channel_title="Sidemen",
            observed_at=now - timedelta(days=days_ago),
        )
    _watch(
        store,
        event="recent-1",
        channel_id="UC-sidemen",
        channel_title="Sidemen",
        observed_at=now - timedelta(days=5),
    )

    intelligence = YouTubeIntelligenceService(store)
    intelligence.rebuild(now=now)
    snapshot = intelligence.snapshot(now=now)
    sidemen = snapshot["channels"][0]

    assert sidemen["trend"] == "falling"
    assert sidemen["lifecycle"] == "waning"
    assert sidemen["windows"]["recent_30d"]["count"] == 1


def test_snapshot_reads_labels_from_derived_signals_not_raw_observations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _store(tmp_path)
    now = datetime(2026, 7, 23, tzinfo=UTC)
    _watch(
        store,
        event="watch-derived",
        channel_id="UC-derived",
        channel_title="Derived Channel",
        observed_at=now - timedelta(days=1),
    )
    intelligence = YouTubeIntelligenceService(store)
    intelligence.rebuild(now=now)
    monkeypatch.setattr(
        store,
        "list_observation_details",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("raw observations were reread")
        ),
    )

    snapshot = intelligence.snapshot(now=now)

    assert snapshot["channels"][0]["label"] == "Derived Channel"


def test_rebuild_removes_projection_state_for_deleted_observations(tmp_path: Path) -> None:
    store = _store(tmp_path)
    now = datetime(2026, 7, 23, tzinfo=UTC)
    _watch(
        store,
        event="watch-deleted",
        channel_id="UC-deleted",
        channel_title="Deleted Channel",
        observed_at=now - timedelta(days=1),
    )
    intelligence = YouTubeIntelligenceService(store)
    intelligence.rebuild(now=now)

    connection = store._connect()
    try:
        with connection:
            connection.execute(
                "DELETE FROM observations WHERE event_key = ?",
                ("watch-deleted",),
            )
    finally:
        connection.close()

    rebuilt = intelligence.rebuild(now=now)
    snapshot = intelligence.snapshot(now=now)

    assert rebuilt["signals_removed"] == 1
    assert snapshot["channels"] == []
    assert snapshot["counts"]["channels"] == 0


def test_incremental_rebuild_uses_checkpoint_and_recomputes_only_new_subjects(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    now = datetime(2026, 7, 23, tzinfo=UTC)
    _watch(
        store,
        event="watch-initial",
        channel_id="UC-incremental",
        channel_title="Incremental Channel",
        observed_at=now - timedelta(days=2),
    )
    intelligence = YouTubeIntelligenceService(store)

    first = intelligence.rebuild_incremental(now=now)
    second = intelligence.rebuild_incremental(now=now)

    assert first["mode"] == "backfill"
    assert first["initial_backfill"] is True
    assert first["observations_scanned"] == 1
    assert second["mode"] == "incremental"
    assert second["initial_backfill"] is False
    assert second["observations_scanned"] == 0
    assert second["subjects_recomputed"] == 0

    _watch(
        store,
        event="watch-new",
        channel_id="UC-incremental",
        channel_title="Incremental Channel",
        observed_at=now,
    )
    third = intelligence.rebuild_incremental(now=now)

    assert third["mode"] == "incremental"
    assert third["observations_scanned"] == 1
    assert third["signals_created"] == 1
    assert third["subjects_recomputed"] == 1
    assert intelligence.status()["ready"] is True
    assert intelligence.snapshot(now=now)["readiness"]["phase"] == "ready"
