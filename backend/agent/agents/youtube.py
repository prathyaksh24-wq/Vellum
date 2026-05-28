from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import SpecialistResponse


class YoutubeAgent:
    name = "YoutubeAgent"

    _SOURCE_KEYWORDS = (
        "youtube",
        "yt",
    )

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = Path(vault_root)

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._SOURCE_KEYWORDS)

    def answer(self, query: str) -> SpecialistResponse:
        return SpecialistResponse(
            agent=self.name,
            status="needs_fetch",
            summary="full YouTube specialist execution deferred until the YoutubeAgent ingestion loop is wired.",
            analysis="The first routing slice can identify YouTube-style requests, but it does not fetch or summarize videos yet.",
            confidence=0.35,
        )

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None
