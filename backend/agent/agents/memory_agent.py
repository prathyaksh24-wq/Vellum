from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import MemoryProposal, SpecialistResponse
from agent.tools.capabilities.memory_service import MemoryCapabilityService


class MemoryAgent:
    name = "MemoryAgent"

    _KEYWORDS = (
        "memory",
        "memories",
        "remember",
        "preference",
        "preferences",
    )
    _CONTEXT_PATTERNS = (
        r"(?<!\w)memory\s+context(?!\w)",
        r"(?<!\w)context\s+pack(?!\w)",
        r"(?<!\w)long[-\s]?term\s+context(?!\w)",
        r"(?<!\w)remembered\s+context(?!\w)",
    )

    def __init__(self, vault_root: Path, memory_service: MemoryCapabilityService | None = None) -> None:
        self.vault_root = Path(vault_root)
        self.memory_service = memory_service or MemoryCapabilityService(
            vault_root=self.vault_root,
            sessions_db=self.vault_root.parent / "data" / "memory" / "sessions.db",
        )

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._KEYWORDS) or any(
            re.search(pattern, lowered) is not None for pattern in self._CONTEXT_PATTERNS
        )

    def answer(self, query: str) -> SpecialistResponse:
        try:
            context_pack = self.memory_service.build_context_pack(
                {"query": query, "thread_id": "default", "agent_name": self.name}
            )
            proposals = [self._proposal_for_query(query)]
            accepted = self.review_proposals(proposals)
        except Exception as exc:
            return SpecialistResponse(
                agent=self.name,
                status="error",
                summary="MemoryAgent could not build memory context right now.",
                analysis=_sanitize_error(exc),
                confidence=0.2,
            )

        cards = context_pack.get("cards", [])
        if cards:
            card_text = "; ".join(_summarize_card(card) for card in cards[:3])
            summary = f"Relevant memory cards: {card_text}. A reviewed proposal was prepared."
        else:
            summary = "No matching memory cards were found; a reviewed proposal was prepared."

        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis="Built a context pack and reviewed memory proposals through memory capability service.",
            confidence=0.8,
            memory_proposals=accepted,
        )

    def review_proposals(self, proposals: list[MemoryProposal]) -> list[MemoryProposal]:
        result = self.memory_service.review_proposals({"proposals": proposals})
        return [
            MemoryProposal(**item)
            for item in result.get("accepted", [])
        ]

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None

    def _proposal_for_query(self, query: str) -> MemoryProposal:
        claim = _claim_from_query(query)
        return MemoryProposal(
            scope="memory",
            claim=claim,
            evidence=query,
            confidence=0.8,
        )


def _summarize_card(card: object) -> str:
    if not isinstance(card, dict):
        return ""
    text = str(card.get("text", "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:240]


def _sanitize_error(exc: Exception) -> str:
    message = re.sub(r"\s+", " ", str(exc)).strip()
    message = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted-email]", message)
    return message[:200]


def _claim_from_query(query: str) -> str:
    cleaned = re.sub(r"\s+", " ", query).strip().strip("\"'")
    patterns = (
        r"(?i)^remember\s+that\s+(.+)$",
        r"(?i)^remember\s+(.+)$",
        r"(?i)^what\s+should\s+you\s+remember\s+about\s+(.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, cleaned)
        if match:
            cleaned = match.group(1).strip()
            break
    cleaned = re.sub(r"(?i)^i\s+prefer\b", "User prefers", cleaned)
    cleaned = re.sub(r"(?i)^i\s+like\b", "User likes", cleaned)
    cleaned = re.sub(r"(?i)^my\s+", "User's ", cleaned)
    if not re.match(r"(?i)^user\b", cleaned):
        cleaned = f"User asked to remember: {cleaned}"
    return cleaned.rstrip(".") + "."
