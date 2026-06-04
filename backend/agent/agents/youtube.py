from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import SpecialistResponse
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService


class YoutubeAgent:
    name = "YoutubeAgent"

    _SOURCE_KEYWORDS = (
        "youtube",
        "yt",
    )

    def __init__(self, vault_root: Path, youtube_service: YoutubeCapabilityService | None = None) -> None:
        self.vault_root = Path(vault_root)
        self.youtube_service = youtube_service or YoutubeCapabilityService()

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._SOURCE_KEYWORDS)

    def answer(self, query: str) -> SpecialistResponse:
        try:
            result = self.youtube_service.search_videos({"query": query, "max_results": 5})
        except Exception as exc:
            return SpecialistResponse(
                agent=self.name,
                status="error",
                summary="YoutubeAgent could not fetch YouTube data right now.",
                analysis=f"YouTube search failed: {self._sanitize_error(exc)}",
                confidence=0.2,
            )
        if result.get("status") == "unsupported":
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary=result["message"],
                analysis=(
                    "YoutubeAgent is wired to the shared YouTube capability interface; "
                    "the read-only backend is next."
                ),
                confidence=0.35,
            )
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=str(result),
            analysis="Used youtube.search_videos.",
            confidence=0.7,
        )

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None

    def _sanitize_error(self, exc: Exception) -> str:
        message = str(exc).replace("\r", " ").replace("\n", " ").strip()
        message = re.sub(
            r"(?i)(api[_-]?key|access[_-]?token|authorization|bearer|client[_-]?secret|password)\s*[:=]?\s*\S+",
            r"\1=[redacted]",
            message,
        )
        message = re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "[redacted]", message)
        if not message:
            message = exc.__class__.__name__
        return f"{exc.__class__.__name__}: {message}"[:160]
