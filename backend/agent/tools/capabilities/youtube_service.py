from __future__ import annotations

import re
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.config import get_settings
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry
from agent.tools.serpapi import SerpApiClient
from agent.tools.web import extract_web_sources, web_search


logger = logging.getLogger(__name__)

SearchVideosBackend = Callable[[str, int], list[dict[str, Any]]]
SerpApiSearchBackend = Callable[[str, int], list[dict[str, Any]]]
SerpApiTranscriptBackend = Callable[[str], dict[str, Any] | None]
WebSearchBackend = Callable[[str, int], list[dict[str, Any]]]
TranscriptBackend = Callable[[dict[str, Any]], dict[str, Any] | None]


class YoutubeCapabilityService:
    def __init__(
        self,
        vault_root: Path,
        search_backend: SearchVideosBackend | None = None,
        serpapi_search_backend: SerpApiSearchBackend | None = None,
        serpapi_transcript_backend: SerpApiTranscriptBackend | None = None,
        web_search_backend: WebSearchBackend | None = None,
        transcript_backend: TranscriptBackend | None = None,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.serpapi_search_backend = serpapi_search_backend or self._default_serpapi_search_videos
        self.serpapi_transcript_backend = serpapi_transcript_backend or self._default_serpapi_fetch_transcript
        self.web_search_backend = web_search_backend or self._default_web_search_videos
        self.search_backend = search_backend or self._default_search_videos
        self.transcript_backend = transcript_backend or self._default_fetch_transcript

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        allowed_agents = frozenset({"YoutubeAgent", "VellumAgent", "ResearchAgent", "MemoryAgent"})
        registry.register(
            CapabilityRecord(
                name="youtube.search_videos",
                namespace="youtube",
                access=CapabilityAccess.READ,
                allowed_agents=allowed_agents,
                stream_label="Searched YouTube",
                adapter=self.search_videos,
            )
        )
        registry.register(
            CapabilityRecord(
                name="youtube.fetch_transcript",
                namespace="youtube",
                access=CapabilityAccess.READ,
                allowed_agents=allowed_agents,
                stream_label="Fetched YouTube transcript",
                adapter=self.fetch_transcript,
            )
        )
        return registry

    def search_videos(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        max_results = _positive_int(payload.get("max_results"), default=5)
        if not query:
            return {"action": "youtube.search_videos", "items": []}
        items = [
            self._normalize_video(item)
            for item in self.search_backend(query, max_results)
        ]
        ranked_items = _rank_youtube_videos(query, items)
        return {"action": "youtube.search_videos", "items": ranked_items[:max_results]}

    def fetch_transcript(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.transcript_backend(payload)
        if not result:
            return {
                "action": "youtube.fetch_transcript",
                "video_id": str(payload.get("video_id") or ""),
                "transcript": "",
                "path": "",
            }
        return {
            "action": "youtube.fetch_transcript",
            "video_id": str(result.get("video_id") or payload.get("video_id") or ""),
            "transcript": str(result.get("transcript") or ""),
            "path": str(result.get("path") or ""),
        }

    def _normalize_video(self, item: dict[str, Any]) -> dict[str, str]:
        url = _string(item.get("url") or item.get("watchUrl") or item.get("link"))
        video_id = _string(
            item.get("video_id")
            or item.get("videoId")
            or item.get("id")
            or _video_id_from_url(url)
        )
        return {
            "video_id": video_id,
            "title": _string(item.get("title") or item.get("name")),
            "url": url or (f"https://www.youtube.com/watch?v={video_id}" if video_id else ""),
            "channel": _string(item.get("channel") or item.get("channelName") or item.get("author")),
            "published_at": _string(item.get("published_at") or item.get("publishedAt") or item.get("date")),
            "description": _string(item.get("description") or item.get("snippet") or item.get("body")),
            "transcript": _string(item.get("transcript") or item.get("transcriptText")),
        }

    def _default_search_videos(self, query: str, max_results: int) -> list[dict[str, Any]]:
        try:
            serpapi_items = self.serpapi_search_backend(query, max_results)
        except Exception as exc:
            logger.warning("YouTube SerpAPI search failed; falling back to web search: %s", exc)
            serpapi_items = []
        if serpapi_items:
            return serpapi_items[:max_results]
        return self.web_search_backend(query, max_results)[:max_results]

    def _default_serpapi_search_videos(self, query: str, max_results: int) -> list[dict[str, Any]]:
        settings = get_settings()
        if not settings.serpapi_api_key:
            return []
        return SerpApiClient(api_key=settings.serpapi_api_key, log_path=settings.serpapi_log_path).youtube_search(
            query,
            max_results=max_results * 3,
        )

    def _default_web_search_videos(self, query: str, max_results: int) -> list[dict[str, Any]]:
        output = web_search.invoke({"query": f"site:youtube.com/watch {query}"})
        sources = extract_web_sources(str(output))
        candidates = [
            {
                "title": source.get("title", ""),
                "url": source.get("url", ""),
                "description": source.get("snippet", ""),
            }
            for source in sources
            if "youtube.com" in str(source.get("url", ""))
        ]
        return candidates[: max_results * 3]

    def _default_fetch_transcript(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        video_id = str(payload.get("video_id") or "").strip()
        if video_id:
            try:
                result = self.serpapi_transcript_backend(video_id)
            except Exception as exc:
                logger.warning("YouTube SerpAPI transcript failed; falling back to local cards: %s", exc)
                result = None
            if result and result.get("transcript"):
                return result
        query = str(payload.get("query") or "").strip().lower()
        youtube_root = self.vault_root / "Library" / "Youtube"
        if not youtube_root.exists():
            return None

        for path in sorted(youtube_root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            lowered = text.lower()
            if video_id and video_id not in text:
                continue
            if query and query not in lowered:
                continue
            transcript = _extract_transcript(text)
            return {
                "video_id": video_id or _frontmatter_value(text, "video_id"),
                "transcript": transcript,
                "path": path.relative_to(self.vault_root).as_posix(),
            }
        return None

    def _default_serpapi_fetch_transcript(self, video_id: str) -> dict[str, Any] | None:
        settings = get_settings()
        if not settings.serpapi_api_key:
            return None
        return SerpApiClient(api_key=settings.serpapi_api_key, log_path=settings.serpapi_log_path).youtube_transcript(
            video_id
        )


def _extract_transcript(text: str) -> str:
    match = re.search(r"(?is)^##\s+Transcript\s*(.+?)(?:\n##\s+|\Z)", text, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    body = re.sub(r"(?s)^---.*?---\s*", "", text).strip()
    return body


def _frontmatter_value(text: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*\"?([^\"\n]+)\"?\s*$", text)
    return match.group(1).strip() if match else ""


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _rank_youtube_videos(query: str, items: list[dict[str, str]]) -> list[dict[str, str]]:
    candidates = [item for item in items if item.get("url") and not _is_low_quality_youtube_result(item)]
    return sorted(
        candidates,
        key=lambda item: _youtube_video_score(query, item),
        reverse=True,
    )


def _youtube_video_score(query: str, item: dict[str, str]) -> int:
    title = item.get("title", "")
    channel = item.get("channel", "")
    description = item.get("description", "")
    published_at = item.get("published_at", "")
    haystack = f"{title} {description}".lower()
    query_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 2 and token not in {"the", "and", "for", "vs", "v"}
    }
    matched_tokens = sum(1 for token in query_tokens if token in haystack)

    score = matched_tokens * 10
    if _is_official_youtube_channel(channel):
        score += 100
    if "official" in haystack:
        score += 20
    if "highlight" in haystack:
        score += 10
    score += _published_at_score(published_at)
    if "youtube.com/watch" in item.get("url", "") or "youtu.be/" in item.get("url", ""):
        score += 5
    return score


def _is_low_quality_youtube_result(item: dict[str, str]) -> bool:
    text = f"{item.get('title', '')} {item.get('description', '')} {item.get('channel', '')}".lower()
    blocked_terms = (
        "dream league",
        "efootball",
        "fantasy score",
        "fifa 23",
        "fifa 24",
        "fifa 25",
        "fifa 26",
        "football gaming",
        "gameplay",
        "gaming",
        "pes ",
        "pes20",
        "pes21",
        "pes22",
        "pes23",
        "pes24",
        "simulation",
        "simulated",
    )
    return any(term in text for term in blocked_terms)


def _is_official_youtube_channel(channel: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", channel.lower()).strip()
    official_channels = {
        "fifa",
        "uefa",
        "nba",
        "formula 1",
        "f1",
        "premier league",
        "arsenal",
        "espn",
        "sky sports",
        "nbc sports",
        "fox soccer",
    }
    return normalized in official_channels


def _published_at_score(value: str) -> int:
    normalized = value.lower()
    if "hour" in normalized or "minute" in normalized or "today" in normalized:
        return 30
    if "day" in normalized or "yesterday" in normalized:
        return 25
    if "week" in normalized:
        return 15
    if "month" in normalized:
        return 5
    if "year" in normalized:
        return -10
    return 0


def _video_id_from_url(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", url)
    return match.group(1) if match else ""


def _string(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
