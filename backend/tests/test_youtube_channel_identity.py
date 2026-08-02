from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent.knowledge.models import (
    ObservationActor,
    ObservationInput,
    Sensitivity,
)
from agent.knowledge.store import KnowledgeStore
from agent.plugins.youtube_channel_identity import (
    ChannelIdentityRecord,
    YouTubeChannelIdentityService,
)
from agent.plugins.youtube_intelligence import YouTubeIntelligenceService


def test_reconcile_preserves_renamed_channel_as_aliases_idempotently(
    tmp_path: Path,
) -> None:
    store = KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs")
    service = YouTubeChannelIdentityService(store)
    now = datetime(2026, 8, 1, tzinfo=UTC)
    records = [
        ChannelIdentityRecord(
            channel_id="UC-stable",
            title="Original Name",
            observed_at=now - timedelta(days=30),
        ),
        ChannelIdentityRecord(
            channel_id="UC-stable",
            title="Current Name",
            observed_at=now,
        ),
    ]

    first = service.reconcile(records)
    identity_before_repeat = service.resolve("UC-stable")
    second = service.reconcile(records)
    identity = service.resolve("UC-stable")

    assert first == {
        "records_scanned": 2,
        "entities_created": 1,
        "entities_existing": 0,
        "aliases_created": 2,
        "aliases_existing": 0,
    }
    assert second == {
        "records_scanned": 2,
        "entities_created": 0,
        "entities_existing": 1,
        "aliases_created": 0,
        "aliases_existing": 2,
    }
    assert identity_before_repeat is not None
    assert identity is not None
    assert identity["updated_at"] == identity_before_repeat["updated_at"]
    assert identity["external_id"] == "UC-stable"
    assert identity["canonical_name"] == "Current Name"
    assert set(identity["aliases"]) == {"Original Name", "Current Name"}
    assert identity["entity_id"] == service.resolve("UC-stable")["entity_id"]
    assert service.resolve_many(["UC-stable", "missing"]) == {
        "uc-stable": identity,
    }


def test_reconcile_keeps_known_title_when_latest_record_has_no_title(
    tmp_path: Path,
) -> None:
    store = KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs")
    service = YouTubeChannelIdentityService(store)
    observed_at = datetime(2026, 8, 1, tzinfo=UTC)

    service.reconcile(
        [
            ChannelIdentityRecord(
                channel_id="UC-stable",
                title="",
                observed_at=observed_at + timedelta(days=1),
            ),
            ChannelIdentityRecord(
                channel_id="UC-stable",
                title="Known Name",
                observed_at=observed_at,
            ),
        ]
    )

    identity = service.resolve("UC-stable")
    assert identity is not None
    assert identity["canonical_name"] == "Known Name"
    assert identity["aliases"] == ["Known Name"]


def test_profile_requires_review_for_shared_alias_across_channel_ids(
    tmp_path: Path,
) -> None:
    store = KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs")
    service = YouTubeChannelIdentityService(store)
    observed_at = datetime(2026, 8, 1, tzinfo=UTC)
    service.reconcile(
        [
            ChannelIdentityRecord(
                channel_id="UC-one",
                title="Shared Name",
                observed_at=observed_at,
            ),
            ChannelIdentityRecord(
                channel_id="UC-two",
                title="Shared Name",
                observed_at=observed_at,
            ),
        ]
    )

    profile = service.profile(limit=10)
    one = service.resolve("UC-one")
    two = service.resolve("UC-two")

    assert one["entity_id"] != two["entity_id"]
    assert profile["local_only"] is True
    assert profile["counts"] == {
        "entities": 2,
        "aliases": 2,
        "collision_candidates": 1,
    }
    assert profile["candidates"] == [
        {
            "candidate_id": profile["candidates"][0]["candidate_id"],
            "alias": "Shared Name",
            "external_ids": ["UC-one", "UC-two"],
            "entity_ids": sorted([one["entity_id"], two["entity_id"]]),
            "reason": "shared_alias_distinct_external_ids",
            "requires_review": True,
            "auto_merge": False,
        }
    ]


def test_intelligence_rebuild_materializes_channel_identity_for_snapshot(
    tmp_path: Path,
) -> None:
    store = KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs")
    now = datetime(2026, 8, 1, tzinfo=UTC)
    store.record_observation(
        ObservationInput(
            origin="youtube_takeout",
            action="youtube.watch",
            actor=ObservationActor.IMPORTED,
            trigger="google_takeout",
            event_key="watch-old-name",
            payload={
                "video_id": "video-old",
                "channel_id": "UC-stable",
                "channel_title": "Original Name",
            },
            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
            confidence=1.0,
            observed_at=now - timedelta(days=30),
        )
    )
    store.record_observation(
        ObservationInput(
            origin="youtube_takeout",
            action="youtube.watch",
            actor=ObservationActor.IMPORTED,
            trigger="google_takeout",
            event_key="watch-current-name",
            payload={
                "video_id": "video-current",
                "channel_id": "UC-stable",
                "channel_title": "Current Name",
            },
            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
            confidence=1.0,
            observed_at=now,
        )
    )

    intelligence = YouTubeIntelligenceService(store)
    rebuilt = intelligence.rebuild(now=now)
    channel = intelligence.snapshot(now=now)["channels"][0]

    assert rebuilt["identity"] == {
        "records_scanned": 2,
        "entities_created": 1,
        "entities_existing": 0,
        "aliases_created": 2,
        "aliases_existing": 0,
    }
    assert channel["entity_id"]
    assert channel["channel_id"] == "UC-stable"
    assert channel["label"] == "Current Name"
    assert set(channel["aliases"]) == {"Original Name", "Current Name"}
