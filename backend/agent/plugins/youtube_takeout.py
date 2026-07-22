"""Private, idempotent Google Takeout ingestion for YouTube activity."""

from __future__ import annotations

import codecs
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
import zipfile
from zoneinfo import ZoneInfo

from agent.knowledge.ingestion import IngestionCoordinator, IngestionResult
from agent.knowledge.models import (
    ExternalPolicy,
    IngestionJobInput,
    ObservationActor,
    ObservationInput,
    Sensitivity,
    SourceItemInput,
)
from agent.knowledge.store import KnowledgeStore


ORIGIN = "youtube_takeout"
WATCH_ACTION = "youtube.watch"
SEARCH_ACTION = "youtube.search"
ACTIVITY_ACTION = "youtube.activity"
_EVENT_DATE = re.compile(
    r"(?<!\d)((?:[1-9]|[12]\d|3[01]) [A-Za-z]{3,4} \d{4}, (?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d)\s+([A-Z]{2,5})"
)
_TIMEZONES = {"IST": "Asia/Kolkata", "UTC": "UTC", "GMT": "UTC"}


class _ActivityParser(HTMLParser):
    def __init__(self, callback: Callable[[str, list[dict[str, str]]], None]) -> None:
        super().__init__(convert_charrefs=True)
        self.callback = callback
        self.capturing = False
        self.depth = 0
        self.text: list[str] = []
        self.links: list[dict[str, Any]] = []
        self.current_link: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "div" and not self.capturing and "outer-cell" in str(attributes.get("class") or "").split():
            self.capturing = True
            self.depth = 1
            self.text = []
            self.links = []
            self.current_link = None
            return
        if not self.capturing:
            return
        if tag == "div":
            self.depth += 1
        elif tag == "a":
            self.current_link = {"href": str(attributes.get("href") or ""), "text": []}
            self.links.append(self.current_link)

    def handle_endtag(self, tag: str) -> None:
        if not self.capturing:
            return
        if tag == "a":
            self.current_link = None
        elif tag == "div":
            self.depth -= 1
            if self.depth == 0:
                links = [
                    {"href": str(link["href"]), "text": _clean_text(" ".join(link["text"]))}
                    for link in self.links
                ]
                self.callback(_clean_text(" ".join(self.text)), links)
                self.capturing = False

    def handle_data(self, data: str) -> None:
        if not self.capturing:
            return
        self.text.append(data)
        if self.current_link is not None:
            self.current_link["text"].append(data)


class YouTubeTakeoutImporter:
    def __init__(self, *, store: KnowledgeStore, account_id: str) -> None:
        self.store = store
        self.account_id = account_id.strip() or "primary"

    def run(self, archive_path: str | Path, *, idempotency_key: str, requested_by: str = "user") -> dict[str, Any]:
        path = Path(archive_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError("YouTube Takeout archive was not found")
        coordinator = IngestionCoordinator(self.store)
        return coordinator.run(
            IngestionJobInput(
                connector="youtube_takeout",
                account_id=self.account_id,
                job_type="activity_archive",
                idempotency_key=idempotency_key,
                requested_by=requested_by,
                lease_seconds=86400,
            ),
            operation=lambda _cursor: self._import_archive(path),
        )

    def history(self, *, kind: str = "watch", limit: int = 20) -> dict[str, Any]:
        normalized = "search" if kind.casefold() == "search" else "watch"
        action = SEARCH_ACTION if normalized == "search" else WATCH_ACTION
        total = self.store.count_observations(origin=ORIGIN, action=action)
        rows = self.store.list_observation_details(origin=ORIGIN, action=action, limit=limit)
        items = []
        for row in rows:
            payload = dict(row.get("payload") or {})
            payload["occurred_at"] = str(row.get("observed_at") or "")
            items.append(payload)
        return {"available": total > 0, "kind": normalized, "total": total, "items": items}

    def _import_archive(self, path: Path) -> IngestionResult:
        archive_hash = _file_sha256(path)
        observations: list[ObservationInput] = []
        stats = {
            "watch_events": 0,
            "search_events": 0,
            "other_events": 0,
            "events_skipped": 0,
            "media_files_inventoried": 0,
            "media_bytes_inventoried": 0,
        }
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            media = [item for item in infos if not item.is_dir() and "/videos/" in item.filename and item.filename.lower().endswith(".mp4")]
            stats["media_files_inventoried"] = len(media)
            stats["media_bytes_inventoried"] = sum(item.file_size for item in media)
            manifest = {
                "archive_sha256": archive_hash,
                "archive_bytes": path.stat().st_size,
                "entry_count": len(infos),
                "media": [
                    {"entry": item.filename, "bytes": item.file_size, "crc32": f"{item.CRC:08x}"}
                    for item in media
                ],
            }
            manifest_source = self.store.upsert_source(
                SourceItemInput(
                    kind="youtube_takeout_archive",
                    external_id=f"youtube:takeout:{self.account_id}:{archive_hash}",
                    account_id=self.account_id,
                    title="YouTube Takeout archive",
                    content=json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                    source_path=str(path),
                    sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                    external_policy=ExternalPolicy.DENY_RAW,
                    trust="official_takeout",
                    metadata={"connector": "youtube_takeout", "archive_sha256": archive_hash},
                )
            )
            source_id = str(manifest_source["source_id"])
            for info in infos:
                lowered = info.filename.casefold()
                if lowered.endswith("/history/watch-history.html"):
                    self._parse_history(archive, info, source_id, archive_hash, observations, stats)
                elif lowered.endswith("/history/search-history.html"):
                    self._parse_history(archive, info, source_id, archive_hash, observations, stats)

        inserted = self.store.record_observations(observations)
        stats["observations_created"] = inserted["created"]
        stats["observations_existing"] = inserted["existing"]
        return IngestionResult(
            stats=stats,
            cursor=archive_hash,
            cursor_state={
                "archive_sha256": archive_hash,
                "watch_events": stats["watch_events"],
                "search_events": stats["search_events"],
            },
        )

    def _parse_history(
        self,
        archive: zipfile.ZipFile,
        info: zipfile.ZipInfo,
        source_id: str,
        archive_hash: str,
        observations: list[ObservationInput],
        stats: dict[str, int],
    ) -> None:
        def capture(text: str, links: list[dict[str, str]]) -> None:
            kind = "watch"
            event = _event_from_activity(kind, text, links)
            if event is None:
                kind = "search"
                event = _event_from_activity(kind, text, links)
            if event is None:
                occurred_at = _event_timestamp(text)
                if occurred_at is not None:
                    kind = "other"
                    event = _generic_activity(text, links, occurred_at)
            if event is None:
                stats["events_skipped"] += 1
                return
            event_identity = "\x1f".join(
                [kind, event["occurred_at"].isoformat(), event.get("video_id", ""), event.get("query", ""), event.get("title", "")]
            )
            event_key = f"youtube:takeout:{self.account_id}:{sha256(event_identity.encode('utf-8')).hexdigest()}"
            payload = {key: value for key, value in event.items() if key != "occurred_at"}
            observations.append(
                ObservationInput(
                    origin=ORIGIN,
                    action={"watch": WATCH_ACTION, "search": SEARCH_ACTION}.get(kind, ACTIVITY_ACTION),
                    actor=ObservationActor.IMPORTED,
                    trigger="google_takeout",
                    source_id=source_id,
                    event_key=event_key,
                    payload={**payload, "archive_sha256": archive_hash},
                    sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
                    confidence=1.0,
                    observed_at=event["occurred_at"],
                )
            )
            stats[f"{kind}_events"] += 1

        parser = _ActivityParser(capture)
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        with archive.open(info) as source:
            while chunk := source.read(1024 * 1024):
                parser.feed(decoder.decode(chunk))
            parser.feed(decoder.decode(b"", final=True))
        parser.close()


def _event_from_activity(kind: str, text: str, links: list[dict[str, str]]) -> dict[str, Any] | None:
    occurred_at = _event_timestamp(text)
    if occurred_at is None:
        return None
    if kind == "search":
        search_link = next((link for link in links if "/results" in urlparse(link["href"]).path), None)
        if search_link is None:
            return None
        query = str(parse_qs(urlparse(search_link["href"]).query).get("search_query", [search_link["text"]])[0]).strip()
        return {"query": query, "url": search_link["href"], "occurred_at": occurred_at}

    video_link = next(
        (link for link in links if urlparse(link["href"]).path in {"/watch", "/shorts"} or "/shorts/" in urlparse(link["href"]).path),
        None,
    )
    if video_link is None:
        return None
    parsed = urlparse(video_link["href"])
    video_id = str(parse_qs(parsed.query).get("v", [parsed.path.rsplit("/", 1)[-1] if "/shorts/" in parsed.path else ""])[0])
    channel_link = next((link for link in links if "/channel/" in urlparse(link["href"]).path), None)
    channel_id = urlparse(channel_link["href"]).path.rsplit("/", 1)[-1] if channel_link else ""
    return {
        "video_id": video_id,
        "title": video_link["text"],
        "channel_id": channel_id,
        "channel_title": channel_link["text"] if channel_link else "",
        "url": video_link["href"],
        "occurred_at": occurred_at,
    }


def _generic_activity(text: str, links: list[dict[str, str]], occurred_at: datetime) -> dict[str, Any]:
    activity_links = [
        link["href"]
        for link in links
        if link["href"] and "myaccount.google.com/activitycontrols" not in link["href"]
    ][:5]
    summary = text.split("Products:", 1)[0].strip()
    return {
        "summary": summary[:1000],
        "urls": activity_links,
        "occurred_at": occurred_at,
    }


def _event_timestamp(text: str) -> datetime | None:
    match = _EVENT_DATE.search(text)
    if match is None:
        return None
    normalized = re.sub(r"\bSept\b", "Sep", match.group(1), flags=re.I)
    naive = datetime.strptime(normalized, "%d %b %Y, %H:%M:%S")
    zone = ZoneInfo(_TIMEZONES.get(match.group(2), "UTC"))
    return naive.replace(tzinfo=zone).astimezone(UTC)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_text(value: str) -> str:
    return " ".join(value.split()).strip()
