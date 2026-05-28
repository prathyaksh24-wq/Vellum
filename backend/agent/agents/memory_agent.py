from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import MemoryProposal, SpecialistResponse


class MemoryAgent:
    name = "MemoryAgent"

    _KEYWORDS = (
        "memory",
        "memories",
        "remember",
        "preference",
        "preferences",
    )

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = Path(vault_root)

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._KEYWORDS)

    def answer(self, query: str) -> SpecialistResponse:
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="MemoryAgent first slice does not mutate shared memory directly; it only prepares reviewable proposals.",
            analysis="Shared memory updates remain parent-owned until proposal review and persistence are implemented.",
            confidence=0.8,
            memory_proposals=self.review_proposals(),
        )

    def review_proposals(self) -> list[MemoryProposal]:
        return [
            MemoryProposal(
                scope="memory",
                claim="MemoryAgent should propose durable memories for review instead of mutating shared memory directly.",
                evidence="Task 4 specialist stub contract requires reviewable proposals and no direct shared-memory mutation.",
                confidence=0.75,
            )
        ]

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None
