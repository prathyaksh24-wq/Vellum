"""Local YouTube interest projections derived from canonical observations."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import re
from typing import Any, Callable, Iterator

from agent.knowledge.models import (
    EvidenceClass,
    ObservationActor,
    Sensitivity,
    UserSignalInput,
)
from agent.knowledge.store import KnowledgeStore
from agent.plugins.youtube_channel_identity import (
    ChannelIdentityRecord,
    YouTubeChannelIdentityService,
)


ORIGIN = "youtube_takeout"
WATCH_ACTION = "youtube.watch"
SEARCH_ACTION = "youtube.search"
CHANNEL_CATEGORY = "youtube_channel"
SEARCH_CATEGORY = "youtube_search_theme"
MIN_SEARCH_THEME_EVIDENCE = 2
PAGE_SIZE = 500

SignalFactory = Callable[[dict[str, Any]], UserSignalInput | None]


class YouTubeIntelligenceService:
    """Build and read rebuildable YouTube preference projections."""

    def __init__(
        self,
        store: KnowledgeStore,
        identities: YouTubeChannelIdentityService | None = None,
    ) -> None:
        self.store = store
        self.identities = identities or YouTubeChannelIdentityService(store)

    def rebuild(self, *, now: datetime | None = None) -> dict[str, Any]:
        reference = _utc(now)
        scanned = 0
        created = 0
        existing = 0
        subjects: set[str] = set()
        expected_event_keys: set[str] = set()
        identity_records: list[ChannelIdentityRecord] = []

        for action, factory in (
            (WATCH_ACTION, self._channel_signal),
            (SEARCH_ACTION, self._search_signal),
        ):
            for rows in self._observation_pages(action):
                signals: list[UserSignalInput] = []
                for row in rows:
                    scanned += 1
                    if action == WATCH_ACTION:
                        if identity_record := self._channel_identity_record(row):
                            identity_records.append(identity_record)
                    signal = factory(row)
                    if signal is None:
                        continue
                    signals.append(signal)
                    subjects.add(signal.subject_key)
                    expected_event_keys.add(signal.event_key)
                result = self.store.record_user_signals(signals, recompute=False)
                created += result["created"]
                existing += result["existing"]

        identity_result = self.identities.reconcile(identity_records)
        pruned = self.store.prune_user_signals(
            event_key_prefix="youtube:intelligence:",
            categories=(CHANNEL_CATEGORY, SEARCH_CATEGORY),
            keep_event_keys=expected_event_keys,
        )
        subjects.update(pruned["subject_keys"])
        recomputed = 0
        for subject_key in sorted(subjects):
            if self.store.recompute_preference(subject_key, now=reference) is not None:
                recomputed += 1
        return {
            "observations_scanned": scanned,
            "signals_created": created,
            "signals_existing": existing,
            "signals_removed": int(pruned["removed"]),
            "subjects_recomputed": recomputed,
            "identity": identity_result,
        }

    def snapshot(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
        query: str = "",
    ) -> dict[str, Any]:
        reference = _utc(now)
        bounded_limit = max(1, min(int(limit), 100))
        query_terms = _query_terms(query)
        trend_filter = _trend_filter(query) if not query_terms else ""
        categories = _query_categories(query)
        channels = (
            self._preference_items(
                category=CHANNEL_CATEGORY,
                limit=bounded_limit,
                query_terms=query_terms,
                trend_filter=trend_filter,
            )
            if CHANNEL_CATEGORY in categories
            else []
        )
        search_themes = (
            self._preference_items(
                category=SEARCH_CATEGORY,
                limit=bounded_limit,
                query_terms=query_terms,
                trend_filter=trend_filter,
            )
            if SEARCH_CATEGORY in categories
            else []
        )
        projection_updated_at = max(
            [str(item["updated_at"]) for item in channels + search_themes],
            default="",
        )
        return {
            "generated_at": reference.isoformat(),
            "projection_updated_at": projection_updated_at,
            "local_only": True,
            "source": ORIGIN,
            "counts": {
                "channels": self.store.count_preferences(category=CHANNEL_CATEGORY),
                "search_themes": self.store.count_preferences(
                    category=SEARCH_CATEGORY,
                    min_evidence_count=MIN_SEARCH_THEME_EVIDENCE,
                ),
            },
            "returned_counts": {
                "channels": len(channels),
                "search_themes": len(search_themes),
            },
            "channels": channels,
            "search_themes": search_themes,
        }

    def _preference_items(
        self,
        *,
        category: str,
        limit: int,
        query_terms: set[str],
        trend_filter: str,
    ) -> list[dict[str, Any]]:
        if query_terms:
            evidence = self.store.search_latest_signal_metadata(
                category=category,
                query_terms=query_terms,
                limit=500,
            )
            states = self.store.preferences_for_subjects(evidence)
            if category == SEARCH_CATEGORY:
                states = [
                    state
                    for state in states
                    if int(state["evidence_count"]) >= MIN_SEARCH_THEME_EVIDENCE
                ]
        else:
            states = self.store.list_ranked_preferences(
                category=category,
                limit=limit,
                trend=trend_filter,
                min_evidence_count=(
                    MIN_SEARCH_THEME_EVIDENCE
                    if category == SEARCH_CATEGORY
                    else 0
                ),
            )
            evidence = self.store.latest_signal_metadata(
                str(state["subject_key"]) for state in states
            )
        identity_by_channel: dict[str, dict] = {}
        if category == CHANNEL_CATEGORY:
            channel_ids = [
                str(
                    (
                        evidence.get(str(state["subject_key"]), {}).get(
                            "metadata"
                        )
                        or {}
                    ).get("channel_id")
                    or ""
                )
                for state in states
            ]
            identity_by_channel = self.identities.resolve_many(channel_ids)

        items = []
        for state in states:
            signal = evidence.get(str(state["subject_key"]), {})
            source = dict(signal.get("metadata") or {})
            item = {
                "subject_key": state["subject_key"],
                "label": source.get(
                    "channel_title" if category == CHANNEL_CATEGORY else "query",
                    "",
                ),
                "current_score": state["current_score"],
                "trend": state["trend"],
                "lifecycle": state["lifecycle"],
                "confidence": state["confidence"],
                "historical_peak": state["historical_peak"],
                "evidence_count": state["evidence_count"],
                "latest_observation_at": signal.get("observed_at", ""),
                "windows": state["windows"],
                "updated_at": state["updated_at"],
            }
            if category == CHANNEL_CATEGORY:
                channel_id = str(source.get("channel_id") or "")
                identity = (
                    identity_by_channel.get(channel_id.casefold())
                    if channel_id
                    else None
                )
                item["channel_id"] = channel_id
                item["entity_id"] = (
                    str(identity["entity_id"]) if identity is not None else ""
                )
                item["aliases"] = (
                    list(identity["aliases"]) if identity is not None else []
                )
                if identity is not None:
                    item["label"] = str(identity["canonical_name"])
            items.append(item)
        if query_terms:
            single_term = next(iter(query_terms)) if len(query_terms) == 1 else ""
            items.sort(
                key=lambda item: (
                    int(bool(single_term) and _normalized(str(item.get("label") or "")) == single_term),
                    int(item["evidence_count"]),
                    float(item["current_score"]),
                    float(item["confidence"]),
                ),
                reverse=True,
            )
        else:
            items.sort(
                key=lambda item: (
                    float(item["current_score"]),
                    float(item["confidence"]),
                    int(item["evidence_count"]),
                ),
                reverse=True,
            )
        return items[:limit]

    def _observation_pages(self, action: str) -> Iterator[list[dict[str, Any]]]:
        offset = 0
        while True:
            rows = self.store.list_observation_details(
                origin=ORIGIN,
                action=action,
                limit=PAGE_SIZE,
                offset=offset,
            )
            if not rows:
                return
            yield rows
            if len(rows) < PAGE_SIZE:
                return
            offset += len(rows)

    @staticmethod
    def _channel_identity_record(
        row: dict[str, Any],
    ) -> ChannelIdentityRecord | None:
        payload = dict(row.get("payload") or {})
        channel_id = str(payload.get("channel_id") or "").strip()
        if not channel_id:
            return None
        observed_at = _parse_time(row.get("observed_at"))
        if observed_at is None:
            return None
        return ChannelIdentityRecord(
            channel_id=channel_id,
            title=str(payload.get("channel_title") or "").strip(),
            observed_at=observed_at,
            source_id=row.get("source_id"),
        )

    def _channel_signal(self, row: dict[str, Any]) -> UserSignalInput | None:
        payload = dict(row.get("payload") or {})
        channel_id = str(payload.get("channel_id") or "").strip()
        channel_title = str(payload.get("channel_title") or "").strip()
        if not channel_id and not channel_title:
            return None
        identity = channel_id or f"title-{_digest(_normalized(channel_title))}"
        return self._signal(
            row,
            subject_key=f"youtube:channel:{identity}",
            category=CHANNEL_CATEGORY,
            signal_type="watch_event",
            value=0.6,
            metadata={
                "channel_id": channel_id,
                "channel_title": channel_title,
                "evidence": "watch_event_only",
                "completion_unknown": True,
            },
        )

    def _search_signal(self, row: dict[str, Any]) -> UserSignalInput | None:
        payload = dict(row.get("payload") or {})
        query = str(payload.get("query") or "").strip()
        normalized = _normalized(query)
        if not normalized:
            return None
        return self._signal(
            row,
            subject_key=f"youtube:search:{_digest(normalized)}",
            category=SEARCH_CATEGORY,
            signal_type="search_event",
            value=0.45,
            metadata={
                "query": query,
                "normalized_query": normalized,
                "evidence": "search_event_only",
                "endorsement_unknown": True,
            },
        )

    @staticmethod
    def _signal(
        row: dict[str, Any],
        *,
        subject_key: str,
        category: str,
        signal_type: str,
        value: float,
        metadata: dict[str, Any],
    ) -> UserSignalInput:
        event_key = str(row.get("event_key") or row.get("id") or "")
        return UserSignalInput(
            subject_key=subject_key,
            category=category,
            signal_type=signal_type,
            event_key=f"youtube:intelligence:{event_key}"[:500],
            value=value,
            weight=1.0,
            actor=ObservationActor.IMPORTED,
            evidence_class=EvidenceClass.IMPORTED,
            preference_evidence=True,
            source_id=row.get("source_id"),
            observation_id=str(row.get("id") or "") or None,
            observed_at=_parse_time(row.get("observed_at")),
            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
            metadata=metadata,
        )

def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    clean = str(value or "").strip()
    if not clean:
        return None
    try:
        return _utc(datetime.fromisoformat(clean.replace("Z", "+00:00")))
    except ValueError:
        return None


def _utc(value: datetime | None) -> datetime:
    result = value or datetime.now(UTC)
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _query_terms(value: str) -> set[str]:
    ignored = {
        "about", "changed", "change", "channel", "channels", "from",
        "gaining", "have", "interest", "interests", "losing", "more",
        "repeat", "repeated", "repeatedly", "search", "searched", "theme",
        "themes", "what", "which",
        "youtube",
    }
    return {
        term
        for term in re.findall(r"[a-z0-9]+", value.casefold())
        if len(term) > 3 and term not in ignored
    }


def _query_categories(value: str) -> set[str]:
    normalized = value.casefold()
    asks_for_search = re.search(r"\bsearch(?:ed|es|ing)?\b", normalized) is not None
    asks_for_channel = re.search(r"\bchannels?\b", normalized) is not None
    if asks_for_search and not asks_for_channel:
        return {SEARCH_CATEGORY}
    if asks_for_channel and not asks_for_search:
        return {CHANNEL_CATEGORY}
    return {CHANNEL_CATEGORY, SEARCH_CATEGORY}


def _trend_filter(value: str) -> str:
    normalized = value.casefold()
    if any(term in normalized for term in ("losing", "declining", "falling", "waning", "less interested")):
        return "falling"
    if any(term in normalized for term in ("gaining", "rising", "more interested")):
        return "rising"
    return ""


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:20]
