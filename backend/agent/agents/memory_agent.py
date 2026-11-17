from __future__ import annotations

import re
from pathlib import Path
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from agent.agents.base import MemoryProposal, SpecialistResponse, SpecialistSource
from agent.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from agent.tools.capabilities.memory_service import MemoryCapabilityService


class MemoryAgent:
    name = "MemoryAgent"

    _KEYWORDS = (
        "memory",
        "memories",
        "remember",
        "forget",
        "preference",
        "preferences",
    )

    def __init__(
        self,
        memory_service: MemoryCapabilityService | None = None,
        sessions_db: Path | None = None,
        tool_registry: ToolRegistry | None = None,
        orchestrator_provider: Callable[[], Any] | None = None,
    ) -> None:
        # With an orchestrator, MemoryAgent reads and writes Vellum's real
        # memory store (the one recall, the summary and the Memory page use).
        self.orchestrator_provider = orchestrator_provider
        self.tool_registry = tool_registry
        self.memory_service = memory_service or (
            None
            if tool_registry is not None
            else self._default_memory_service(sessions_db)
        )

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._KEYWORDS)

    def answer(self, query: str) -> SpecialistResponse:
        clean_query = query.strip()
        orchestrator = self._orchestrator()
        if orchestrator is not None:
            if self._is_remember_instruction(clean_query):
                return self._save_to_store(orchestrator, clean_query)
            if self._is_forget_instruction(clean_query):
                return self._forget_in_store(orchestrator, clean_query)
            return self._lookup_in_store(orchestrator, clean_query)
        if self._is_remember_instruction(clean_query):
            return self._answer_remember_instruction(clean_query)
        return self._answer_memory_lookup(clean_query)

    def _orchestrator(self) -> Any | None:
        if self.orchestrator_provider is None:
            return None
        try:
            orchestrator = self.orchestrator_provider()
        except Exception:  # noqa: BLE001 - fall back to the capability service
            return None
        if getattr(orchestrator, "store", None) is None:
            return None
        if not orchestrator.store.get_settings().get("memory_enabled", True):
            return None
        return orchestrator

    def _save_to_store(self, orchestrator: Any, query: str) -> SpecialistResponse:
        from agent.memory.orchestrator import _candidate_kind, _memory_title
        from agent.observability.activity import emit_activity
        from agent.privacy.classifier import DataClass, classify

        text = self._sentence(self._memory_text_from_instruction(query))
        if classify(text)[0] == DataClass.RED and not orchestrator.store.get_settings().get("include_sensitive", False):
            return SpecialistResponse(
                agent=self.name, status="answered", confidence=0.9,
                summary="That looks like sensitive information, so I didn't save it. "
                        "Turn on \"Include sensitive topics\" in memory settings if you want me to keep things like this.",
                analysis="Refused: RED privacy class with include_sensitive off.",
            )
        kind = _candidate_kind(text)
        scope = "user_profile" if kind in {"preference", "correction"} else "global"
        existing = {str(item.get("text") or "").casefold() for item in orchestrator.store.list_saved()}
        if text.casefold() in existing:
            return SpecialistResponse(agent=self.name, status="answered", confidence=0.9,
                                      summary=f"I already remember that: {text}",
                                      analysis="Duplicate of a saved memory; nothing written.")
        memory = orchestrator.save_explicit_memory(kind=kind, text=text, source_thread_id="memory-agent",
                                                   confidence=0.95, scope=scope, origin="stated")
        emit_activity("memory_save", "memory", label=f"Saved to memory · {_memory_title(text)}", status="completed",
                      memory_id=memory["id"], text=text, memory_kind=kind)
        return SpecialistResponse(
            agent=self.name, status="answered", confidence=0.95,
            summary=f"Saved to memory: {text}",
            analysis=f"Saved memory {memory['id']} ({kind}, {scope}) through the Memory Orchestrator.",
            sources=[SpecialistSource(kind="memory", title=memory.get("title") or text[:60],
                                      path_or_url=f"memory:{memory['id']}", freshness="recent")],
        )

    def _forget_in_store(self, orchestrator: Any, query: str) -> SpecialistResponse:
        from agent.memory.recall import keyword_rank
        from agent.observability.activity import emit_activity

        target = re.sub(r"^(please\s+)?(forget|stop remembering|don'?t remember)(\s+(that|about))?\s+", "",
                        query.strip(), flags=re.I).strip(" .") or query
        matches = keyword_rank(target, orchestrator.store.list_saved(), limit=3)
        if not matches:
            return SpecialistResponse(agent=self.name, status="answered", confidence=0.7,
                                      summary="I couldn't find a saved memory matching that.",
                                      analysis="No keyword match among saved memories.")
        for memory in matches:
            orchestrator.store.set_suppressed(memory["id"], True)
            emit_activity("memory_save", "memory", label=f"Stopped using · {memory.get('title')}",
                          status="completed", memory_id=memory["id"], action="suppress")
        titles = "; ".join(str(memory.get("title") or memory.get("text")) for memory in matches)
        return SpecialistResponse(
            agent=self.name, status="answered", confidence=0.85,
            summary=f"I'll stop using: {titles}. To delete permanently, remove it on the Memory page.",
            analysis=f"Suppressed memories {[m['id'] for m in matches]}; deletion needs the user's confirmation.",
        )

    def _lookup_in_store(self, orchestrator: Any, query: str) -> SpecialistResponse:
        from agent.memory.recall import select_relevant_memories

        pool = [item for item in orchestrator.store.list_saved() if not item.get("suppressed")]
        chosen, method = select_relevant_memories(query, pool, limit=8)
        if not chosen and re.search(r"\b(?:about me|know about me|remember about me|what do you remember)\b", query, re.I):
            chosen, method = pool[:8], "overview"
        reflection = ""
        provider = orchestrator.provider_extensions.get("hindsight") if orchestrator.provider_extensions else None
        if provider is not None and hasattr(provider, "reflect"):
            try:
                reflection = provider.reflect(query)
            except Exception:  # noqa: BLE001 - reflection is optional
                reflection = ""
        if not chosen and not reflection:
            return SpecialistResponse(agent=self.name, status="needs_fetch", confidence=0.35,
                                      summary="I don't have anything saved about that yet.",
                                      analysis="No saved memory matched; Hindsight reflection empty or unavailable.")
        lines = [f"- {item.get('text')}" for item in chosen]
        if reflection:
            lines.append(f"\nFrom long-term memory: {reflection}")
        return SpecialistResponse(
            agent=self.name, status="answered", confidence=0.8,
            summary="\n".join(lines),
            analysis=f"Read {len(chosen)} saved memories ({method}) from the Memory Orchestrator"
                     + ("; Hindsight reflect" if reflection else "") + ".",
            sources=[SpecialistSource(kind="memory", title=str(item.get("title") or "memory"),
                                      path_or_url=f"memory:{item['id']}", freshness="historical")
                     for item in chosen[:5]],
        )

    def _answer_memory_lookup(self, query: str) -> SpecialistResponse:
        pack = self._memory_invoke("memory.build_context_pack", {"query": query, "agent_name": self.name})
        cards = pack.get("cards") or []
        if not cards:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="MemoryAgent did not find matching durable memory cards.",
                analysis="Used memory.build_context_pack; no cards matched the query.",
                confidence=0.35,
            )

        lines = []
        sources: list[SpecialistSource] = []
        for index, card in enumerate(cards[:3], start=1):
            text = str(card.get("text") or "").strip()
            path = str(card.get("path") or "")
            first_line = self._first_content_line(text)
            first_line = re.sub(r'^(?:the )?user prefers\b', 'You prefer', first_line, flags=re.I)
            first_line = re.sub(r'^(?:the )?user is\b', 'You are', first_line, flags=re.I)
            lines.append(first_line)
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
            summary=" ".join(lines),
            analysis="Used memory.build_context_pack and memory.search_cards through MemoryCapabilityService.",
            sources=sources,
            confidence=0.76,
        )

    def _answer_remember_instruction(self, query: str) -> SpecialistResponse:
        memory_text = self._memory_text_from_instruction(query)
        claim = f"User asked Vellum to remember: {self._sentence(memory_text)}"
        proposal_result = self._memory_invoke(
            "memory.propose_card",
            {
                "scope": "memory",
                "claim": claim,
                "evidence": query,
                "confidence": 0.8,
            }
        )
        reviewed = self._memory_invoke(
            "memory.review_proposals",
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

    def _memory_invoke(self, name: str, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke(name, payload, agent_name=self.name)
        action = name.rsplit(".", 1)[-1]
        return getattr(self.memory_service, action)(payload)

    def _default_memory_service(self, sessions_db: Path | None):
        from agent.tools.capabilities.memory_service import MemoryCapabilityService

        from agent.config import REPO_ROOT

        return MemoryCapabilityService(
            sessions_db=sessions_db or REPO_ROOT / "data" / "memory" / "memory-agent-sessions.db",
        )

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None

    def _is_remember_instruction(self, query: str) -> bool:
        lowered = query.lower().strip()
        return re.match(r"^(please\s+)?(remember|memorize|note)\b", lowered) is not None

    def _is_forget_instruction(self, query: str) -> bool:
        return re.match(r"^(please\s+)?(forget|stop remembering|don'?t remember)\b", query.lower().strip()) is not None

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
