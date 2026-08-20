from __future__ import annotations

from typing import Any

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.contracts.books import books_envelope_payload
from agent.tools.registry import ToolRegistry


class BooksAgent:
    name = "BooksAgent"

    def __init__(self, *, tool_registry: ToolRegistry) -> None:
        self.tool_registry = tool_registry

    def can_handle(self, query: str) -> bool:
        _ = query
        return False

    def answer(self, query: str) -> SpecialistResponse:
        clean_query = str(query or "").strip()
        if not clean_query:
            return self._response(
                status="blocked",
                envelope_status="failed",
                summary="BooksAgent requires a question.",
                uncertainty=["No Book question was supplied."],
            )

        activity: list[dict[str, Any]] = []
        errors: list[str] = []
        try:
            knowledge = self.tool_registry.invoke(
                "books.knowledge_query",
                {"query": clean_query},
                agent_name=self.name,
            )
            evidence = list(knowledge.get("evidence") or [])
            activity.append(
                {"name": "books.knowledge_query", "status": "completed", "count": len(evidence)}
            )
        except Exception:
            evidence = []
            errors.append("books.knowledge_query")
            activity.append({"name": "books.knowledge_query", "status": "error"})

        try:
            skill_result = self.tool_registry.invoke(
                "books.skill_lookup",
                {"query": clean_query},
                agent_name=self.name,
            )
            skills = list(skill_result.get("skills") or [])
            activity.append(
                {"name": "books.skill_lookup", "status": "completed", "count": len(skills)}
            )
        except Exception:
            skills = []
            errors.append("books.skill_lookup")
            activity.append({"name": "books.skill_lookup", "status": "error"})

        sources = _safe_sources(evidence, skills)
        if errors and not sources:
            return self._response(
                status="error",
                envelope_status="failed",
                summary="BooksAgent could not query installed Book evidence.",
                uncertainty=["One or more required Book capabilities were unavailable."],
                activity=activity,
            )
        if sources:
            summary = (
                "BooksAgent found matching installed Book records or Hermes Book skills, "
                "but exact evidence spans are not available for a grounded answer yet."
            )
            uncertainty = ["Exact Book spans have not been loaded or validated for this question."]
            if errors:
                uncertainty.append("Some Book capabilities were unavailable, so the result may be incomplete.")
            return self._response(
                status="needs_fetch",
                envelope_status="partial",
                summary=summary,
                uncertainty=uncertainty,
                sources=sources,
                activity=activity,
            )
        return self._response(
            status="needs_fetch",
            envelope_status="abstained",
            summary="No matching installed Book evidence was found.",
            uncertainty=["No matching installed Book evidence was found."],
            activity=activity,
        )

    def _response(
        self,
        *,
        status: str,
        envelope_status: str,
        summary: str,
        uncertainty: list[str],
        sources: list[SpecialistSource] | None = None,
        activity: list[dict[str, Any]] | None = None,
    ) -> SpecialistResponse:
        return SpecialistResponse(
            agent=self.name,
            status=status,
            summary=summary,
            analysis="Knowledge Core metadata and routed Hermes Book skills only; no unsupported Book claim was produced.",
            sources=sources or [],
            confidence=0.0,
            activity_events=activity or [],
            structured_payload=books_envelope_payload(
                answer=summary,
                status=envelope_status,
                uncertainty=uncertainty,
            ),
        )


def _safe_sources(evidence: list[dict[str, Any]], skills: list[dict[str, Any]]) -> list[SpecialistSource]:
    sources: list[SpecialistSource] = []
    for item in evidence[:8]:
        source_id = str(item.get("source_id") or "").strip()
        if not source_id:
            continue
        sources.append(
            SpecialistSource(
                kind="book",
                title=str(item.get("title") or "Installed Book"),
                path_or_url=f"knowledge://sources/{source_id}",
                captured_at=str(item.get("observed_at") or ""),
                freshness="historical",
            )
        )
    for item in skills[:8]:
        name = str(item.get("name") or "").strip()
        if name:
            sources.append(
                SpecialistSource(
                    kind="book",
                    title=str(item.get("description") or name),
                    path_or_url=f"skill://{name}",
                    freshness="historical",
                )
            )
    return sources
