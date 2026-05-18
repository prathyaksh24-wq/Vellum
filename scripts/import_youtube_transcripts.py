#!/usr/bin/env python3
"""Fetch YouTube channel transcripts into the Obsidian vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from textwrap import shorten
from typing import Any, Callable


DEFAULT_ACTOR = "majdijm/youtube-channel-scraper"
DEFAULT_OLDEST_POST_DATE = "2005-01-01"


@dataclass(frozen=True)
class ChannelConfig:
    key: str
    name: str
    handle: str
    url: str


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    title: str
    url: str
    channel: str
    handle: str
    published_at: str
    duration: str
    transcript: str
    language: str = "en"
    is_auto_generated: bool | None = None

    @property
    def transcript_hash(self) -> str:
        return hashlib.sha256(self.transcript.encode("utf-8")).hexdigest()[:16]


CHANNELS: dict[str, ChannelConfig] = {
    "moresidemen": ChannelConfig(
        key="moresidemen",
        name="MoreSidemen",
        handle="moresidemen",
        url="https://www.youtube.com/@MoreSidemen",
    ),
    "ksi": ChannelConfig(
        key="ksi",
        name="KSI",
        handle="ksi",
        url="https://www.youtube.com/@KSI",
    ),
    "sidemen": ChannelConfig(
        key="sidemen",
        name="Sidemen",
        handle="sidemen",
        url="https://www.youtube.com/@Sidemen",
    ),
    "betasquad": ChannelConfig(
        key="betasquad",
        name="Beta Squad",
        handle="betasquad",
        url="https://www.youtube.com/@BetaSquad",
    ),
    "matarmstrong": ChannelConfig(
        key="matarmstrong",
        name="Mat Armstrong",
        handle="matarmstrong",
        url="https://www.youtube.com/@MatArmstrongbmx",
    ),
}

Fetcher = Callable[[ChannelConfig, int, str, str, str], list[dict[str, Any]]]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def vault_path(project_root: Path) -> Path:
    env_path = project_root / ".env"
    if not env_path.exists():
        return project_root / "Vault"
    load_dotenv(env_path)
    configured = os.environ.get("OBSIDIAN_VAULT_PATH")
    return Path(configured).expanduser() if configured else project_root / "Vault"


def apify_token(project_root: Path) -> str:
    load_dotenv(project_root / ".env")
    return os.environ.get("APIFY_API_TOKEN", "").strip()


def apify_youtube_actor(project_root: Path) -> str:
    load_dotenv(project_root / ".env")
    return os.environ.get("APIFY_YOUTUBE_ACTOR", DEFAULT_ACTOR).strip() or DEFAULT_ACTOR


def fetch_apify_channel(
    channel_config: ChannelConfig,
    max_videos: int,
    video_type: str,
    actor: str,
    token: str,
) -> list[dict[str, Any]]:
    if not token:
        raise RuntimeError("APIFY_API_TOKEN is required to fetch YouTube transcripts.")

    try:
        from apify_client import ApifyClient
    except ImportError as exc:
        raise RuntimeError("apify-client is required. Install backend requirements first.") from exc

    run_input = {
        "channelUrls": [channel_config.url],
        "oldestPostDate": DEFAULT_OLDEST_POST_DATE,
        "maxVideos": max_videos,
        "videoType": video_type,
        "includeTranscript": True,
        "transcriptLanguage": "en",
        "sortBy": "newest",
    }
    client = ApifyClient(token=token)
    run = client.actor(actor).call(run_input=run_input)
    if run is None:
        return []

    dataset_id = _run_value(run, "defaultDatasetId", "default_dataset_id")
    if not dataset_id:
        return []

    return list(client.dataset(dataset_id).iterate_items())


def _run_value(run: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(run, dict) and key in run:
            return run[key]
        value = getattr(run, key, None)
        if value is not None:
            return value
    return None


def normalize_video(item: dict[str, Any], channel_config: ChannelConfig) -> tuple[YouTubeVideo | None, str | None]:
    video_id = _first_text(item, "videoId", "video_id", "id", "youtube_id")
    url = _first_text(item, "url", "videoUrl", "video_url", "link", "watchUrl", "watch_url")
    if not video_id:
        video_id = video_id_from_url(url)
    if not video_id:
        return None, "missing_video_id"

    transcript = transcript_text(item)
    if not transcript:
        return None, "missing_transcript"

    title = _first_text(item, "title", "videoTitle", "video_title") or f"YouTube Video {video_id}"
    published_at = _first_text(
        item,
        "publishedAt",
        "published_at",
        "publishDate",
        "publish_date",
        "date",
        "uploadDate",
        "upload_date",
    ) or datetime.now(timezone.utc).date().isoformat()
    channel = _first_text(item, "channel", "channelName", "channel_name") or channel_config.name
    language = _first_text(item, "transcriptLanguage", "transcript_language", "language", "languageCode") or "en"
    is_auto_generated = _first_bool(item, "isAutoGenerated", "is_auto_generated", "autoGenerated")

    return (
        YouTubeVideo(
            video_id=video_id,
            title=clean_text(title),
            url=url or f"https://www.youtube.com/watch?v={video_id}",
            channel=clean_text(channel),
            handle=channel_config.handle,
            published_at=normalize_date_text(published_at),
            duration=_first_text(item, "duration", "videoDuration", "length", "lengthText") or "",
            transcript=transcript,
            language=clean_text(language),
            is_auto_generated=is_auto_generated,
        ),
        None,
    )


def transcript_text(item: dict[str, Any]) -> str:
    raw = None
    for key in (
        "transcript",
        "transcriptText",
        "transcript_text",
        "transcriptPlainText",
        "transcript_plain_text",
        "subtitles",
        "captions",
    ):
        value = item.get(key)
        if value:
            raw = value
            break

    if isinstance(raw, str):
        return clean_text(raw)
    if isinstance(raw, list):
        parts = []
        for segment in raw:
            if isinstance(segment, dict):
                text = segment.get("text") or segment.get("caption") or segment.get("line")
                if text:
                    parts.append(str(text))
            elif segment:
                parts.append(str(segment))
        return clean_text(" ".join(parts))
    if isinstance(raw, dict):
        text = raw.get("text") or raw.get("plainText") or raw.get("transcript")
        if isinstance(text, str):
            return clean_text(text)
        segments = raw.get("segments") or raw.get("lines")
        if isinstance(segments, list):
            return transcript_text({"transcript": segments})
    return ""


def _first_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _first_bool(item: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.casefold() in {"true", "false"}:
            return value.casefold() == "true"
    return None


def clean_text(text: str | None) -> str:
    text = (text or "").strip()
    text = re.sub(r"\r\n?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def video_id_from_url(url: str | None) -> str:
    if not url:
        return ""
    patterns = (
        r"[?&]v=([A-Za-z0-9_-]{11})",
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"/shorts/([A-Za-z0-9_-]{11})",
        r"/embed/([A-Za-z0-9_-]{11})",
    )
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""


def normalize_date_text(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return datetime.now(timezone.utc).date().isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    return value.replace("Z", "+00:00")


def published_datetime(value: str) -> datetime:
    normalized = normalize_date_text(value)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
            return datetime.fromisoformat(normalized).replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def slugify(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())[:10]
    return "-".join(words) or "video"


def yaml_quote(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_bool(value: bool | None) -> str:
    if value is None:
        return "null"
    return "true" if value else "false"


def canonical_note_path(base: Path, video: YouTubeVideo) -> Path:
    published = published_datetime(video.published_at)
    filename = f"{published:%Y-%m-%d}-{video.video_id}-{slugify(video.title)}.md"
    return base / "videos" / f"{published:%Y}" / filename


def note_markdown(video: YouTubeVideo, captured_at: str) -> str:
    published = published_datetime(video.published_at)
    title = shorten(video.title.replace("\n", " "), width=90, placeholder="...")
    return f"""---
type: youtube_transcript
channel: {video.channel}
handle: {video.handle}
video_id: {yaml_quote(video.video_id)}
video_url: {yaml_quote(video.url)}
published_at: {yaml_quote(video.published_at)}
captured_at: {yaml_quote(captured_at)}
duration: {yaml_quote(video.duration)}
language: {yaml_quote(video.language)}
is_auto_generated: {yaml_bool(video.is_auto_generated)}
transcript_hash: {yaml_quote(video.transcript_hash)}
tags:
  - youtube
  - {video.handle}
  - transcript
---

# {published:%Y-%m-%d} - {title}

## Video

- Channel: {video.channel}
- URL: {video.url}
- Duration: {video.duration or "unknown"}
- Language: {video.language}
- Auto-generated: {yaml_bool(video.is_auto_generated)}

## Transcript

{video.transcript}
"""


def write_video_note(base: Path, video: YouTubeVideo, captured_at: str) -> Path:
    path = canonical_note_path(base, video)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note_markdown(video, captured_at), encoding="utf-8", newline="\n")
    return path


def read_existing_records(base: Path) -> dict[str, dict[str, Any]]:
    manifest = base / f"{base.name}-transcripts.jsonl"
    if not manifest.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for line in manifest.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        video_id = str(record.get("video_id") or "")
        if video_id:
            records[video_id] = record
    return records


def record_for(video: YouTubeVideo, vault: Path, base: Path, captured_at: str) -> dict[str, Any]:
    note = canonical_note_path(base, video)
    return {
        "video_id": video.video_id,
        "title": video.title,
        "channel": video.channel,
        "handle": video.handle,
        "video_url": video.url,
        "published_at": video.published_at,
        "captured_at": captured_at,
        "duration": video.duration,
        "language": video.language,
        "is_auto_generated": video.is_auto_generated,
        "transcript_hash": video.transcript_hash,
        "note_path": note.relative_to(vault).as_posix(),
    }


def write_jsonl(base: Path, channel_key: str, records: list[dict[str, Any]]) -> None:
    with (base / f"{channel_key}-transcripts.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def wiki_link(note_path: str, label: str) -> str:
    stem = note_path[:-3] if note_path.endswith(".md") else note_path
    return f"[[{stem}|{label}]]"


def write_latest(base: Path, records: list[dict[str, Any]], limit: int, captured_at: str) -> None:
    lines = [
        "---",
        "type: youtube_latest_index",
        f"channel: {base.name}",
        f"captured_at: {yaml_quote(captured_at)}",
        f"video_count: {min(limit, len(records))}",
        "tags:",
        "  - youtube",
        f"  - {base.name}",
        "  - latest",
        "---",
        "",
        f"# {base.name} - Latest {min(limit, len(records))} Videos",
        "",
    ]
    for index, record in enumerate(records[:limit], 1):
        label = shorten(str(record["title"]), width=90, placeholder="...")
        lines.extend(
            [
                f"## {index:02d}. {record['published_at'][:10]} - {label}",
                "",
                f"- Note: {wiki_link(record['note_path'], label)}",
                f"- Video: {record['video_url']}",
                f"- Transcript hash: `{record['transcript_hash']}`",
                "",
            ]
        )
    (base / f"latest-{limit}.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_agent_guide(base: Path, channel: ChannelConfig, records: list[dict[str, Any]]) -> None:
    lines = [
        "---",
        "type: youtube_agent_guide",
        f"channel: {channel.name}",
        f"handle: {channel.handle}",
        f"video_count: {len(records)}",
        "tags:",
        "  - youtube",
        f"  - {channel.handle}",
        "  - agent-memory",
        "---",
        "",
        f"# {channel.name} Agent Guide",
        "",
        "## Retrieval Contract",
        "",
        "- Use these transcripts when the user asks about watched creators, recurring preferences, tone, jokes, group dynamics, or channel-specific context.",
        "- Treat individual video notes as canonical memory atoms.",
        "- Prefer direct transcript evidence over broad assumptions about the channel.",
        f"- Current ingestion scope is {channel.name} when this channel is selected.",
        "",
        "## Channel Preference Context",
        "",
        "- Daily/frequent channels: KSI, Sidemen, MoreSidemen, Mat Armstrong, Beta Squad, Carwow, NDL.",
        "- Seasonal channel: NotYourAverageFlight is mainly relevant during the NBA season, with occasional NFL overlap.",
        "",
    ]
    (base / "agent-guide.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_channel_index(base: Path, channel: ChannelConfig, records: list[dict[str, Any]], captured_at: str) -> None:
    lines = [
        "---",
        "type: youtube_channel_index",
        f"channel: {channel.name}",
        f"handle: {channel.handle}",
        f"captured_at: {yaml_quote(captured_at)}",
        f"video_count: {len(records)}",
        "tags:",
        "  - youtube",
        f"  - {channel.handle}",
        "---",
        "",
        f"# {channel.name} YouTube Archive",
        "",
        "## Start Here",
        "",
        f"- [[Youtube/channels/{channel.key}/latest-5|Latest 5]]",
        f"- [[Youtube/channels/{channel.key}/agent-guide|Agent Guide]]",
        f"- `{channel.key}-transcripts.jsonl` for structured lookup",
        "",
        "## Videos",
        "",
    ]
    for record in records:
        label = shorten(str(record["title"]), width=90, placeholder="...")
        lines.append(f"- {record['published_at'][:10]}: {wiki_link(record['note_path'], label)}")
    (base / "_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_root_index(youtube_root: Path, channels: list[ChannelConfig], captured_at: str) -> None:
    lines = [
        "---",
        "type: youtube_collection",
        f"captured_at: {yaml_quote(captured_at)}",
        "tags:",
        "  - youtube",
        "---",
        "",
        "# YouTube Archive",
        "",
        "## Channels",
        "",
    ]
    for channel in channels:
        lines.append(f"- [[Youtube/channels/{channel.key}/_index|{channel.name}]]")
    (youtube_root / "_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_state(
    base: Path,
    channel: ChannelConfig,
    fetched_count: int,
    added_count: int,
    skipped: list[dict[str, str]],
    duplicate_count: int,
    total_count: int,
) -> None:
    state_dir = base / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "last_run_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "channel": channel.name,
        "handle": channel.handle,
        "fetched_count": fetched_count,
        "added_count": added_count,
        "skipped_count": len(skipped),
        "duplicate_count": duplicate_count,
        "total_count": total_count,
        "skipped": skipped,
    }
    (state_dir / "youtube_scraper_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run(
    project_root: Path,
    channel_key: str,
    max_videos: int,
    video_type: str,
    dry_run: bool,
    fetcher: Fetcher = fetch_apify_channel,
    token: str | None = None,
    actor: str | None = None,
) -> int:
    channel_key = channel_key.casefold()
    channel = CHANNELS.get(channel_key)
    if channel is None:
        raise ValueError(f"Unknown channel: {channel_key}")
    if max_videos < 1:
        raise ValueError("--max-videos must be at least 1")
    if video_type not in {"long", "short", "all"}:
        raise ValueError("--video-type must be long, short, or all")

    token = apify_token(project_root) if token is None else token
    actor = apify_youtube_actor(project_root) if actor is None else actor
    items = fetcher(channel, max_videos, video_type, actor, token)

    videos: dict[str, YouTubeVideo] = {}
    skipped: list[dict[str, str]] = []
    duplicate_count = 0
    for index, item in enumerate(items):
        video, reason = normalize_video(item, channel)
        if video is None:
            skipped.append({"index": str(index), "reason": reason or "invalid_item"})
            continue
        if video.video_id in videos:
            duplicate_count += 1
            continue
        videos[video.video_id] = video
        if len(videos) >= max_videos:
            break

    if dry_run:
        print(
            json.dumps(
                {
                    "channel": channel.name,
                    "fetched": len(items),
                    "valid": len(videos),
                    "skipped": len(skipped),
                    "duplicates": duplicate_count,
                    "video_ids": list(videos),
                },
                indent=2,
            )
        )
        return 0

    vault = vault_path(project_root)
    youtube_root = vault / "Youtube"
    base = youtube_root / "channels" / channel.key
    base.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    existing = read_existing_records(base)
    added_count = 0
    for video in videos.values():
        if video.video_id not in existing:
            added_count += 1
        write_video_note(base, video, captured_at)
        existing[video.video_id] = record_for(video, vault, base, captured_at)

    records = sorted(existing.values(), key=lambda record: str(record.get("published_at", "")), reverse=True)
    write_jsonl(base, channel.key, records)
    write_latest(base, records, max_videos, captured_at)
    write_agent_guide(base, channel, records)
    write_channel_index(base, channel, records, captured_at)
    write_root_index(youtube_root, list(CHANNELS.values()), captured_at)
    write_state(
        base,
        channel,
        fetched_count=len(items),
        added_count=added_count,
        skipped=skipped,
        duplicate_count=duplicate_count,
        total_count=len(records),
    )

    print(f"Fetched {len(items)} videos, added {added_count}, total unique {len(records)}")
    print(base)
    if skipped:
        print(f"Skipped {len(skipped)} videos; see .state/youtube_scraper_state.json")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="moresidemen", choices=sorted(CHANNELS))
    parser.add_argument("--max-videos", type=int, default=5)
    parser.add_argument("--video-type", default="long", choices=("long", "short", "all"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    try:
        return run(
            project_root=args.project_root.resolve(),
            channel_key=args.channel,
            max_videos=args.max_videos,
            video_type=args.video_type,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"youtube transcript import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
