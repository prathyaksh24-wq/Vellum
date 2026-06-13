from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.parse
import urllib.request

from agent.config import get_settings


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
        results = payload.get("organic_results") or []
        blocks = []
        for item in results[:num]:
            title = _string(item.get("title") or item.get("source") or "Search result")
            link = _string(item.get("link") or item.get("url"))
            snippet = _string(item.get("snippet") or item.get("description"))
            if not link:
                continue
            blocks.append(f"**{title}**\n{snippet}\n{link}")
        return "\n\n".join(blocks) if blocks else "No web results found."

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


def _video_id_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("youtu.be"):
        return parsed.path.strip("/")
    query = urllib.parse.parse_qs(parsed.query)
    return query.get("v", [""])[0]


def _string(value: Any) -> str:
    return "" if value is None else str(value)
