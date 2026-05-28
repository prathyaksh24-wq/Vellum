from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import SpecialistResponse


class XAgent:
    name = "XAgent"

    _KEYWORDS = (
        "twitter",
        "tweet",
        "tweets",
        "latest-50",
    )
    _X_CONTEXT_PATTERNS = (
        r"(?<!\w)post(?:s|ed|ing)?\s+on\s+x(?!\w)",
        r"(?<!\w)x\s+account(?:s)?(?!\w)",
        r"(?<!\w)x\s+feed(?:s)?(?!\w)",
        r"(?<!\w)x\s+post(?:s)?(?!\w)",
        r"(?<!\w)on\s+x(?!\w)",
    )

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = Path(vault_root)

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._KEYWORDS) or any(
            re.search(pattern, lowered) is not None for pattern in self._X_CONTEXT_PATTERNS
        )

    def answer(self, query: str) -> SpecialistResponse:
        return SpecialistResponse(
            agent=self.name,
            status="needs_fetch",
            summary="full X specialist execution deferred until the XAgent ingestion loop is wired.",
            analysis="The first routing slice can identify X-style requests, but it does not fetch or summarize X data yet.",
            confidence=0.35,
        )

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None
