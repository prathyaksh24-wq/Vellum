from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.contracts.books import BookEvidenceAnchor, BooksAgentEnvelope, books_envelope_payload
from agent.tools.registry import ToolRegistry


class BooksAgent:
    name = "BooksAgent"

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        synthesizer: Callable[[str, list[dict[str, Any]]], dict[str, Any]] | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.synthesizer = synthesizer

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
        knowledge_policy: dict[str, Any] = {}
        try:
            knowledge = self.tool_registry.invoke(
                "books.knowledge_query",
                {"query": clean_query},
                agent_name=self.name,
            )
            evidence = list(knowledge.get("evidence") or [])
            knowledge_policy = dict(knowledge.get("policy") or {})
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
        policy_valid = (
            knowledge_policy.get("active_materializations_only") is True
            and knowledge_policy.get("tenant_scoped") is True
            and knowledge_policy.get("source_content") == "untrusted_evidence"
        )
        if evidence and self.synthesizer is not None and policy_valid:
            try:
                envelope = _validated_synthesis(
                    self.synthesizer(clean_query, evidence),
                    evidence,
                    knowledge_policy,
                )
                activity.append(
                    {"name": "books.synthesize", "status": "completed", "count": len(envelope.claims)}
                )
                confidence = (
                    sum(claim.evidence_confidence for claim in envelope.claims)
                    / len(envelope.claims)
                    if envelope.claims
                    else 0.0
                )
                return SpecialistResponse(
                    agent=self.name,
                    status="answered" if envelope.status in {"complete", "partial"} else "needs_fetch",
                    summary=envelope.answer,
                    analysis=(
                        "Synthesized from tenant-scoped active Book materializations; Book text was "
                        "treated as untrusted evidence and could not invoke tools."
                    ),
                    sources=sources,
                    confidence=confidence,
                    activity_events=activity,
                    structured_payload={"books_agent": envelope.model_dump(mode="json")},
                )
            except Exception:
                errors.append("books.synthesize")
                activity.append({"name": "books.synthesize", "status": "error"})

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
        materialization_id = str(item.get("materialization_id") or "").strip()
        chunk_id = str(item.get("chunk_id") or "").strip()
        if not materialization_id or not chunk_id:
            continue
        sources.append(
            SpecialistSource(
                kind="book",
                title=str(item.get("title") or item.get("document_id") or "Installed Book"),
                path_or_url=f"knowledge://books/{materialization_id}#{chunk_id}",
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


def _validated_synthesis(
    draft: dict[str, Any],
    evidence: list[dict[str, Any]],
    retrieval_policy: dict[str, Any],
) -> BooksAgentEnvelope:
    allowed = {
        "answer",
        "answer_claim_ids",
        "claims",
        "judgment",
        "user_learning_events",
        "uncertainty",
        "status",
    }
    payload = {key: value for key, value in dict(draft).items() if key in allowed}
    payload["evidence"] = [anchor.model_dump(mode="json") for anchor in _evidence_anchors(evidence)]
    payload["retrieval_policy"] = retrieval_policy
    envelope = BooksAgentEnvelope.model_validate(payload)
    if not envelope.answer_claim_ids:
        raise ValueError("Books synthesis must ground the answer in at least one claim")
    return envelope


def _evidence_anchors(evidence: list[dict[str, Any]]) -> list[BookEvidenceAnchor]:
    anchors: list[BookEvidenceAnchor] = []
    for item in evidence:
        evidence_id = str(item.get("evidence_id") or "").strip()
        materialization_id = str(item.get("materialization_id") or "").strip()
        document_id = str(item.get("document_id") or "").strip()
        text = str(item.get("text") or "")
        text_hash = str(item.get("text_hash") or "").strip()
        citations = list(item.get("citations") or [])
        citation = dict(citations[0]) if citations else {}
        epub_cfi = str(citation.get("epub_cfi") or "").strip()
        if not evidence_id or not materialization_id or not document_id or not text or not text_hash:
            continue
        if epub_cfi:
            locator_type = "epub_cfi"
            locator = epub_cfi
        else:
            locator_type = "normalized_offset"
            locator = (
                f"{int(citation.get('normalized_start') or 0)}:"
                f"{int(citation.get('normalized_end') or len(text))}"
            )
        anchors.append(
            BookEvidenceAnchor(
                id=evidence_id,
                source_id=materialization_id,
                work_id=document_id,
                edition_id=str(item.get("edition_id") or ""),
                asset_id=str(citation.get("asset_id") or ""),
                section=str(item.get("section_id") or ""),
                locator_type=locator_type,
                locator=locator,
                text_hash=text_hash,
                quote=text,
                validated=True,
            )
        )
    return anchors
