from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import MemoryProposal, SpecialistResponse, SpecialistSource
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

    def __init__(
        self,
        vault_root: Path,
        memory_service: MemoryCapabilityService | None = None,
        sessions_db: Path | None = None,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.memory_service = memory_service or MemoryCapabilityService(
            vault_root=self.vault_root,
            sessions_db=sessions_db or self.vault_root / "Agent" / "Memory" / "memory-agent-sessions.db",
        )

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._KEYWORDS)

    def answer(self, query: str) -> SpecialistResponse:
        clean_query = query.strip()
        if self._is_remember_instruction(clean_query):
            return self._answer_remember_instruction(clean_query)
        return self._answer_memory_lookup(clean_query)

    def _answer_memory_lookup(self, query: str) -> SpecialistResponse:
        pack = self.memory_service.build_context_pack(
            {"query": query, "agent_name": self.name}
        )
        cards = pack.get("cards") or []
        if not cards:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="MemoryAgent did not find matching durable memory cards.",
                analysis="Used memory.build_context_pack; no cards matched the query.",
                confidence=0.35,
            )

        lines = ["MemoryAgent found relevant durable memory:"]
        sources: list[SpecialistSource] = []
        for index, card in enumerate(cards[:3], start=1):
            text = str(card.get("text") or "").strip()
            path = str(card.get("path") or "")
            first_line = self._first_content_line(text)
            lines.append(f"[{index}] {first_line}")
            if path:
                sources.append(
                    SpecialistSource(
                        kind="memory",
                        title=Path(path).stem,
                        path_or_url=path,
                        freshness="historical",
                    )
                )

        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="\n".join(lines),
            analysis="Used memory.build_context_pack and memory.search_cards through MemoryCapabilityService.",
            sources=sources,
            confidence=0.76,
        )

    def _answer_remember_instruction(self, query: str) -> SpecialistResponse:
        memory_text = self._memory_text_from_instruction(query)
        claim = f"User asked Vellum to remember: {self._sentence(memory_text)}"
        proposal_result = self.memory_service.propose_card(
            {
                "scope": "memory",
                "claim": claim,
                "evidence": query,
                "confidence": 0.8,
            }
        )
        reviewed = self.memory_service.review_proposals(
            {"proposals": [proposal_result.get("proposal", {})]}
        )
        proposals = [
            MemoryProposal(**item)
            for item in reviewed.get("accepted", [])
        ]
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="Prepared a reviewed memory proposal for Vellum to decide whether to persist.",
            analysis="Used memory.propose_card and memory.review_proposals through MemoryCapabilityService; no durable memory was written.",
            confidence=0.8,
            memory_proposals=proposals,
        )

    def review_proposals(self, proposals: list[MemoryProposal]) -> list[MemoryProposal]:
        return [proposal for proposal in proposals if proposal.confidence >= 0.75]

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None

    def _is_remember_instruction(self, query: str) -> bool:
        lowered = query.lower().strip()
        return re.match(r"^(please\s+)?(remember|memorize|note)\b", lowered) is not None

    def _memory_text_from_instruction(self, query: str) -> str:
        text = re.sub(
            r"^(please\s+)?(remember|memorize|note)(\s+that)?\s+",
            "",
            query.strip(),
            flags=re.IGNORECASE,
        ).strip()
        return text or query.strip()

    def _sentence(self, text: str) -> str:
        clean = text.strip()
        if not clean:
            return ""
        return clean if clean.endswith((".", "!", "?")) else f"{clean}."

    def _first_content_line(self, text: str) -> str:
        in_frontmatter = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line == "---":
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter or not line or line.startswith("#"):
                continue
            return line[:240]
        return text.strip()[:240] or "Memory card"
