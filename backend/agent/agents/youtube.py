from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
from agent.tools.registry import ToolRegistry


class YoutubeAgent:
    name = "YoutubeAgent"

    _SOURCE_KEYWORDS = (
        "youtube",
        "yt",
    )
    _VIDEO_INTENT_PATTERNS = (
        r"(?<!\w)what\s+did\s+.+\s+upload(?:ed)?(?!\w)",
        r"(?<!\w).+\s+latest\s+upload(?:s)?(?!\w)",
        r"(?<!\w).+\s+latest\s+video(?:s)?(?!\w)",
        r"(?<!\w).+\s+new\s+video(?:s)?(?!\w)",
    )

    def __init__(
        self,
        vault_root: Path,
        youtube_service: YoutubeCapabilityService | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.tool_registry = tool_registry
        self.youtube_service = youtube_service or (
            None if tool_registry is not None else YoutubeCapabilityService(vault_root=self.vault_root)
        )

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._SOURCE_KEYWORDS) or any(
            re.search(pattern, lowered) is not None for pattern in self._VIDEO_INTENT_PATTERNS
        )

    def answer(self, query: str) -> SpecialistResponse:
        try:
            result = self._search_videos({"query": query, "max_results": 5})
        except Exception as exc:
            return SpecialistResponse(
                agent=self.name,
                status="error",
                summary="YoutubeAgent could not fetch YouTube results right now.",
                analysis=f"YouTube search failed: {self._sanitize_error(exc)}",
                confidence=0.2,
            )
        items = result.get("items") or []
        if not items:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="YoutubeAgent did not find matching YouTube videos.",
                analysis="Used youtube.search_videos through YoutubeCapabilityService; no videos matched the query.",
                confidence=0.35,
            )

        lines = [f"YoutubeAgent found {min(len(items), 5)} relevant YouTube result(s):"]
        sources: list[SpecialistSource] = []
        used_transcript = False
        for index, item in enumerate(items[:5], start=1):
            title = str(item.get("title") or "Untitled YouTube video").strip()
            channel = str(item.get("channel") or "").strip()
            description = str(item.get("description") or "").strip()
            transcript = str(item.get("transcript") or "").strip()
            detail = transcript or description
            used_transcript = used_transcript or bool(transcript)
            label = f"[{index}] {title}"
            if channel:
                label += f" by {channel}"
            if detail:
                label += f": {detail[:240]}"
            lines.append(label)
            url = str(item.get("url") or "").strip()
            if url:
                sources.append(
                    SpecialistSource(
                        kind="web",
                        title=title,
                        path_or_url=url,
                        snippet=detail[:500],
                        captured_at=str(item.get("published_at") or ""),
                        freshness="recent",
                    )
                )

        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="\n".join(lines),
            analysis=(
                "Used youtube.search_videos through YoutubeCapabilityService"
                + (" with transcript snippets." if used_transcript else ".")
            ),
            sources=sources,
            confidence=0.72 if sources else 0.55,
        )

    def _search_videos(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("youtube.search_videos", payload, agent_name=self.name)
        return self.youtube_service.search_videos(payload)

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None

    def _sanitize_error(self, exc: Exception) -> str:
        message = str(exc).replace("\r", " ").replace("\n", " ").strip()
        if not message:
            message = exc.__class__.__name__
        return f"{exc.__class__.__name__}: {message}"[:160]
