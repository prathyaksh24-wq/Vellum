from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.parse
import urllib.request

from agent.config import get_settings

GOOGLE_RESULT_SEPARATOR = "\n\n---\n\n"


class SerpApiClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        log_path: Path | str | None = None,
        timeout_seconds: int = 45,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.serpapi_api_key
        self.base_url = base_url or settings.serpapi_base_url
        self.log_path = Path(log_path if log_path is not None else settings.serpapi_log_path)
        self.timeout_seconds = timeout_seconds

    def search(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("SERPAPI_API_KEY is not configured.")

        clean_params = {key: value for key, value in params.items() if value not in (None, "")}
        request_params = {**clean_params, "api_key": self.api_key}
        url = f"{self.base_url}?{urllib.parse.urlencode(request_params, doseq=True)}"
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self._log_search(params=clean_params, payload=payload)
        return payload

    def google_search_text(self, query: str, *, num: int = 5) -> str:
        payload = self.search({"engine": "google", "q": query, "num": num})
        return _google_payload_text(payload, num=num)

    def fresh_google_search_text(self, query: str, *, num: int = 5) -> str:
        for engine in ("google_ai_mode", "google_light", "google"):
            payload = self.search({"engine": engine, "q": query, "num": num})
            text = _google_payload_text(payload, num=num)
            if text != "No web results found.":
                return text
        return "No web results found."

    def fresh_google_search(self, query: str, *, num: int = 5, min_sources: int = 3) -> dict[str, Any]:
        text = ""
        sources: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        engines_used: list[str] = []
        for engine in ("google_ai_mode", "google_light", "google"):
            payload = self.search({"engine": engine, "q": query, "num": num})
            engines_used.append(engine)
            candidate_text = _google_payload_text(payload, num=num)
            if not text and candidate_text != "No web results found.":
                text = candidate_text
            for source in _google_payload_sources(payload, num=num):
                url = source.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                sources.append({**source, "engine": engine})
            if text and len(sources) >= min_sources:
                break
        return {
            "text": text or "No web results found.",
            "sources": sources,
            "engines": engines_used,
        }

    def youtube_search(self, query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
        payload = self.search({"engine": "youtube", "search_query": query})
        results = payload.get("video_results") or payload.get("results") or []
        return [_normalize_youtube_video(item) for item in results[:max_results] if isinstance(item, dict)]

    def youtube_video(self, video_id: str) -> dict[str, Any]:
        return self.search({"engine": "youtube_video", "v": video_id})

    def youtube_transcript(self, video_id: str) -> dict[str, Any]:
        payload = self.search({"engine": "youtube_video_transcript", "v": video_id})
        segments = payload.get("transcript") or payload.get("transcript_results") or []
        text = "\n".join(
            _string(segment.get("text") or segment.get("snippet"))
            for segment in segments
            if isinstance(segment, dict) and (segment.get("text") or segment.get("snippet"))
        ).strip()
        return {
            "video_id": video_id,
            "transcript": text,
            "path": "",
            "segments": segments if isinstance(segments, list) else [],
        }

    def _log_search(self, *, params: dict[str, Any], payload: dict[str, Any]) -> None:
        metadata = payload.get("search_metadata") if isinstance(payload, dict) else {}
        record = {
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "engine": params.get("engine", "google"),
            "params": dict(params),
            "search_id": metadata.get("id") if isinstance(metadata, dict) else "",
            "status": metadata.get("status") if isinstance(metadata, dict) else "",
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")


def _normalize_youtube_video(item: dict[str, Any]) -> dict[str, Any]:
    url = _string(item.get("link") or item.get("url"))
    channel = item.get("channel")
    channel_name = channel.get("name") if isinstance(channel, dict) else channel
    video_id = _string(item.get("video_id") or item.get("videoId") or _video_id_from_url(url))
    return {
        "videoId": video_id,
        "title": _string(item.get("title")),
        "url": url or (f"https://www.youtube.com/watch?v={video_id}" if video_id else ""),
        "channelName": _string(channel_name),
        "publishedAt": _string(item.get("published_date") or item.get("publishedAt") or item.get("date")),
        "description": _string(item.get("description") or item.get("snippet")),
    }


def _google_payload_text(payload: dict[str, Any], *, num: int) -> str:
    blocks: list[str] = []

    answer = _string(payload.get("answer") or payload.get("ai_answer") or payload.get("summary"))
    if answer:
        blocks.append(answer)

    text_blocks = payload.get("text_blocks")
    if isinstance(text_blocks, list):
        for block in text_blocks[:num]:
            text = _string(block.get("text") if isinstance(block, dict) else block)
            if text:
                blocks.append(text)

    for item in _search_items(payload)[:num]:
        if not isinstance(item, dict):
            continue
        title = _string(item.get("title") or item.get("source") or "Search result")
        link = _string(item.get("link") or item.get("url"))
        snippet = _string(item.get("snippet") or item.get("description"))
        if not link:
            continue
        blocks.append(f"**{title}**\n{snippet}\n{link}")

    return GOOGLE_RESULT_SEPARATOR.join(block for block in blocks if block.strip()) or "No web results found."


def _google_payload_sources(payload: dict[str, Any], *, num: int) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for item in _search_items(payload)[:num]:
        if not isinstance(item, dict):
            continue
        url = _string(item.get("link") or item.get("url"))
        if not url:
            continue
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc[4:] if parsed.netloc.startswith("www.") else parsed.netloc
        provider_label = _string(item.get("source") or item.get("displayed_link") or domain)
        favicon_url = _string(item.get("favicon") or item.get("source_icon") or item.get("thumbnail") or item.get("logo"))
        sources.append(
            {
                "title": _string(item.get("title") or provider_label or domain or "Search result"),
                "url": url,
                "snippet": _string(item.get("snippet") or item.get("description"))[:700],
                "domain": domain,
                "favicon_url": favicon_url,
                "provider_label": provider_label or domain,
            }
        )
    return sources


def _search_items(payload: dict[str, Any]) -> list[Any]:
    items: list[Any] = []
    for key in ("references", "organic_results", "top_stories", "news_results"):
        value = payload.get(key)
        if isinstance(value, list):
            items.extend(value)
    return items


def _video_id_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("youtu.be"):
        return parsed.path.strip("/")
    query = urllib.parse.parse_qs(parsed.query)
    return query.get("v", [""])[0]


def _string(value: Any) -> str:
    return "" if value is None else str(value)
