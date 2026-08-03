"""Canonical local identities for observed YouTube channels."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Iterable

from agent.knowledge.models import EntityIdentityInput, Sensitivity
from agent.knowledge.store import KnowledgeStore


YOUTUBE_CHANNEL_ENTITY = "youtube_channel"


@dataclass(frozen=True)
class ChannelIdentityRecord:
    channel_id: str
    title: str
    observed_at: datetime
    source_id: str | None = None


class YouTubeChannelIdentityService:
    """Reconcile channel IDs and observed titles behind one local interface."""

    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def reconcile(
        self,
        records: Iterable[ChannelIdentityRecord],
    ) -> dict[str, int]:
        scanned = 0
        channels: dict[str, dict] = {}
        for record in records:
            scanned += 1
            channel_id = record.channel_id.strip()
            title = record.title.strip()
            if not channel_id:
                continue
            observed_at = _utc(record.observed_at)
            current = channels.setdefault(
                channel_id,
                {
                    "canonical_name": title or channel_id,
                    "observed_at": observed_at,
                    "latest_title_at": observed_at if title else None,
                    "aliases": set(),
                    "source_id": record.source_id,
                },
            )
            if title:
                current["aliases"].add(title)
                latest_title_at = current["latest_title_at"]
                if (
                    latest_title_at is None
                    or observed_at > latest_title_at
                    or (
                        observed_at == latest_title_at
                        and (
                            current["canonical_name"] == channel_id
                            or title > current["canonical_name"]
                        )
                    )
                ):
                    current["canonical_name"] = title
                    current["latest_title_at"] = observed_at
            if observed_at >= current["observed_at"]:
                current["observed_at"] = observed_at
                current["source_id"] = record.source_id

        items = [
            EntityIdentityInput(
                entity_type=YOUTUBE_CHANNEL_ENTITY,
                external_id=channel_id,
                canonical_name=str(channel["canonical_name"]),
                aliases=sorted(channel["aliases"]),
                source_id=channel["source_id"],
                observed_at=channel["observed_at"],
                sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                metadata={"provider": "youtube"},
            )
            for channel_id, channel in sorted(channels.items())
        ]
        result = self.store.record_entity_identities(items)
        return {"records_scanned": scanned, **result}

    def resolve(self, channel_id: str) -> dict | None:
        return self.store.get_entity_identity(
            entity_type=YOUTUBE_CHANNEL_ENTITY,
            external_id=channel_id.strip(),
        )

    def resolve_many(self, channel_ids: Iterable[str]) -> dict[str, dict]:
        return self.store.get_entity_identities(
            entity_type=YOUTUBE_CHANNEL_ENTITY,
            external_ids=channel_ids,
        )

    @staticmethod
    def expected_entity_id(channel_id: str) -> str:
        """Return the deterministic entity ID even before backfill materializes its row."""
        identity_key = channel_id.strip().casefold()
        if not identity_key:
            return ""
        digest = sha256(
            "\x1f".join((YOUTUBE_CHANNEL_ENTITY, identity_key)).encode("utf-8")
        ).hexdigest()[:32]
        return f"ent_{digest}"

    def profile(self, *, limit: int = 100) -> dict:
        raw = self.store.entity_identity_profile(
            entity_type=YOUTUBE_CHANNEL_ENTITY,
            limit=limit,
        )
        candidates = []
        for collision in raw["collisions"]:
            entities = list(collision["entities"])
            entity_ids = sorted(str(entity["entity_id"]) for entity in entities)
            external_ids = sorted(str(entity["external_id"]) for entity in entities)
            fingerprint = "|".join(
                [str(collision["normalized_alias"]), *entity_ids]
            )
            candidates.append(
                {
                    "candidate_id": "ytcol_" + sha256(
                        fingerprint.encode("utf-8")
                    ).hexdigest()[:24],
                    "alias": str(collision["alias"]),
                    "external_ids": external_ids,
                    "entity_ids": entity_ids,
                    "reason": "shared_alias_distinct_external_ids",
                    "requires_review": True,
                    "auto_merge": False,
                }
            )
        return {
            "local_only": True,
            "counts": raw["counts"],
            "candidates": candidates,
        }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
