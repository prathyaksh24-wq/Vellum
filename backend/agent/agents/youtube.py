from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
from agent.tools.registry import ToolRegistry


class YoutubeAgent:
    name = "YoutubeAgent"

    _INTENT_PATTERNS = (
        re.compile(r"(?<!\w)(?:youtube|yt)(?!\w)", re.I),
        re.compile(r"\bwhat\s+did\s+.+\s+upload(?:ed)?\b", re.I),
        re.compile(r"\b(?:latest|new|recent)\s+.+\s+video\b", re.I),
        re.compile(r"\b(?:video|upload|uploaded|transcript)\s+(?:from|by|of)\s+.+", re.I),
    )
    _VIDEO_INTENT_PATTERNS = (
        r"(?<!\w)what\s+did\s+.+\s+upload(?:ed)?(?!\w)",
        r"(?<!\w).+\s+latest\s+upload(?:s)?(?!\w)",
        r"(?<!\w).+\s+latest\s+video(?:s)?(?!\w)",
        r"(?<!\w).+\s+new\s+video(?:s)?(?!\w)",
    )
    _META_FEEDBACK_PATTERNS = (
        r"\b(previous|last|earlier)\s+(response|answer|reply)\b",
        r"\b(i\s+don'?t\s+need|don'?t\s+add|stop\s+adding|remove|hide)\s+.+\b(evidence|source|sources|format|section)\b",
        r"\b(i\s+don'?t\s+like|i\s+like|prefer|feedback)\b.+\b(answer|response|format|evidence|source|sources)\b",
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
        if self._is_meta_feedback(lowered):
            return False
        return any(pattern.search(query) for pattern in self._INTENT_PATTERNS) or any(
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
        providers = {str(provider).strip().lower() for provider in (result.get("providers") or []) if str(provider).strip()}
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
            if url and self._is_youtube_url(url):
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
                + (" via SerpAPI" if "serpapi" in providers else "")
                + (" with transcript snippets." if used_transcript else ".")
            ),
            sources=sources,
            confidence=0.72 if sources else 0.55,
        )

    def _search_videos(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("youtube.search_videos", payload, agent_name=self.name)
        return self.youtube_service.search_videos(payload)

    def _is_youtube_url(self, url: str) -> bool:
        return "youtube.com/watch" in url or "youtu.be/" in url

    def _is_meta_feedback(self, lowered_query: str) -> bool:
        return any(re.search(pattern, lowered_query) is not None for pattern in self._META_FEEDBACK_PATTERNS)

    def _sanitize_error(self, exc: Exception) -> str:
        message = str(exc).replace("\r", " ").replace("\n", " ").strip()
        if not message:
            message = exc.__class__.__name__
        return f"{exc.__class__.__name__}: {message}"[:160]
