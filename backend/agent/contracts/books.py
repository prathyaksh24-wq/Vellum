from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BooksContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BookEvidenceAnchor(BooksContractModel):
    id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    work_id: str = Field(min_length=1)
    edition_id: str = ""
    asset_id: str = ""
    chapter: str = ""
    section: str = ""
    locator_type: Literal[
        "epub_cfi",
        "normalized_offset",
        "file_page",
        "skill_reference",
    ]
    locator: str = Field(min_length=1)
    text_hash: str = ""
    quote: str = ""
    validated: bool = False


class BookClaim(BooksContractModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    origin: Literal["book", "external_source", "user_record", "model_reasoning"]
    form: Literal[
        "quotation",
        "paraphrase",
        "summary",
        "interpretation",
        "comparison",
        "recommendation",
    ]
    speaker: Literal[
        "author",
        "narrator",
        "character",
        "editor",
        "cited_person",
        "user",
        "books_agent",
    ]
    epistemic_status: Literal[
        "asserted",
        "disputed",
        "hypothetical",
        "rhetorical",
        "fictional",
        "uncertain",
    ]
    evidence_ids: list[str] = Field(min_length=1)
    conflicting_evidence_ids: list[str] = Field(default_factory=list)
    evidence_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    interpretation_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    freshness: Literal["timeless", "historical", "time_sensitive", "unknown"] = "unknown"
    sensitivity: Literal["public", "private", "sensitive"] = "public"
    personalization_basis: Literal[
        "none",
        "explicit",
        "observed",
        "inferred",
        "hypothetical",
    ] = "none"
    evidence_status: Literal[
        "verified",
        "supported",
        "interpretive",
        "speculative",
        "insufficient",
    ] = "insufficient"


class BookJudgment(BooksContractModel):
    author_position: str = ""
    strongest_evidence: str = ""
    strongest_counterargument: str = ""
    underlying_factors: list[str] = Field(default_factory=list)
    unresolved_uncertainty: list[str] = Field(default_factory=list)
    conclusion: str = ""


class UserLearningEvent(BooksContractModel):
    id: str = Field(min_length=1)
    kind: Literal[
        "belief",
        "struggle",
        "goal",
        "reaction",
        "book_impact",
        "changing_interest",
        "contradiction",
    ]
    statement: str = Field(min_length=1)
    basis: Literal["explicit", "observed", "inferred"]
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    sensitivity: Literal["private", "sensitive"] = "private"
    observed_at: str = ""


class BooksAgentEnvelope(BooksContractModel):
    schema_version: Literal["books-agent-response-v1"] = "books-agent-response-v1"
    answer: str = Field(min_length=1)
    answer_claim_ids: list[str] = Field(default_factory=list)
    claims: list[BookClaim] = Field(default_factory=list)
    evidence: list[BookEvidenceAnchor] = Field(default_factory=list)
    judgment: BookJudgment | None = None
    user_learning_events: list[UserLearningEvent] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    status: Literal["complete", "partial", "abstained", "failed"]

    @model_validator(mode="after")
    def validate_evidence_graph(self) -> Self:
        claim_by_id = _unique_by_id(self.claims, "claim")
        evidence_by_id = _unique_by_id(self.evidence, "evidence")
        if len(set(self.answer_claim_ids)) != len(self.answer_claim_ids):
            raise ValueError("answer_claim_ids must be unique")
        if self.status == "complete" and not self.answer_claim_ids:
            raise ValueError("complete answers must reference at least one claim")
        unknown_answer_claims = set(self.answer_claim_ids) - set(claim_by_id)
        if unknown_answer_claims:
            raise ValueError("answer_claim_ids must reference claims in this envelope")
        for claim in self.claims:
            referenced = set(claim.evidence_ids) | set(claim.conflicting_evidence_ids)
            if referenced - set(evidence_by_id):
                raise ValueError("claim evidence_ids must reference evidence in this envelope")
            if claim.form == "quotation":
                anchors = [evidence_by_id[item] for item in claim.evidence_ids]
                if not any(anchor.validated and anchor.text_hash and anchor.quote for anchor in anchors):
                    raise ValueError("quotation claims require a validated quoted span and text hash")
        for event in self.user_learning_events:
            if set(event.evidence_ids) - set(evidence_by_id):
                raise ValueError("user learning evidence_ids must reference evidence in this envelope")
        return self


def books_envelope_payload(
    *,
    answer: str,
    status: Literal["complete", "partial", "abstained", "failed"],
    uncertainty: list[str] | None = None,
) -> dict[str, dict]:
    envelope = BooksAgentEnvelope(
        answer=answer,
        uncertainty=uncertainty or [],
        status=status,
    )
    return {"books_agent": envelope.model_dump(mode="json")}


def _unique_by_id(items: list[BooksContractModel], label: str) -> dict[str, BooksContractModel]:
    result = {str(item.id): item for item in items}
    if len(result) != len(items):
        raise ValueError(f"{label} identifiers must be unique")
    return result
