from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BooksContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BooksDiscoveryTask(BooksContractModel):
    """Typed host request; it carries intent, never permission or user identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    operation: Literal["discover", "verify"]
    query: str = Field(default="", max_length=300)
    objective: Literal["user_discovery", "vellum_exploration"] = "user_discovery"
    candidate_id: str = Field(default="", max_length=160)
    max_candidates: int = Field(default=6, ge=1, le=20)

    @model_validator(mode="after")
    def validate_operation(self) -> Self:
        if self.operation == "discover" and (not self.query or self.candidate_id):
            raise ValueError("Discovery requires a query and no candidate ID")
        if self.operation == "verify" and (self.query or not self.candidate_id):
            raise ValueError("Verification requires a candidate ID and no query")
        return self

    @property
    def capability(self) -> str:
        return "books.discover" if self.operation == "discover" else "books.verify_candidate"

    def fingerprint(self) -> str:
        return sha256(json.dumps(self.model_dump(), sort_keys=True).encode()).hexdigest()


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
    user_position: str = "unknown"
    vellum_position: str = ""
    strongest_evidence: str = ""
    strongest_counterargument: str = ""
    underlying_factors: list[str] = Field(default_factory=list)
    unresolved_uncertainty: list[str] = Field(default_factory=list)
    conclusion: str = ""


class BookRetrievalPolicy(BooksContractModel):
    receipt_id: str = ""
    destination: Literal["local", "external"]
    active_materializations_only: bool
    tenant_scoped: bool
    source_content: Literal["untrusted_evidence"]
    whole_chunks_only: bool
    local_only_excluded: bool


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
        "taste",
        "preference",
        "principle",
        "emotional_state",
        "current_situation",
        "practical_need",
    ]
    statement: str = Field(min_length=1, max_length=8000)
    basis: Literal["explicit", "inferred"]
    actor: Literal["user", "connector"] = "user"
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    sensitivity: Literal["private", "sensitive"] = "private"
    lifecycle: Literal["proposed"] = "proposed"
    scope: str = Field(default="books", min_length=1, max_length=120)
    permitted_uses: list[Literal["context", "personalization", "wisdom"]] = Field(
        default_factory=lambda: ["context"],
        min_length=1,
        max_length=3,
    )
    source_agent: Literal["BooksAgent"] = "BooksAgent"
    observed_at: str = ""
    valid_from: str = ""
    valid_to: str = ""
    expires_at: str = ""

    @model_validator(mode="after")
    def enforce_proposal_boundary(self) -> Self:
        if self.sensitivity == "sensitive" and (
            self.basis != "explicit" or self.actor != "user"
        ):
            raise ValueError("sensitive Book learning requires explicit user evidence")
        if self.kind in {"emotional_state", "current_situation"} and not (
            self.valid_to or self.expires_at
        ):
            raise ValueError("temporary Book learning requires a time bound")
        return self


class BookWisdomProposal(BooksContractModel):
    id: str = Field(min_length=1)
    wisdom_type: Literal[
        "useful_principle",
        "recurring_tension",
        "situational_connection",
        "counterargument",
        "cross_book_pattern",
        "unresolved_question",
    ]
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=12000)
    author_perspective: str = Field(min_length=1, max_length=12000)
    user_perspective: str = Field(min_length=1, max_length=12000)
    vellum_perspective: str = Field(min_length=1, max_length=12000)
    explanation: str = Field(min_length=1, max_length=12000)
    user_learning_event_id: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    conflicting_evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: list[str] = Field(default_factory=list, max_length=50)
    sensitivity: Literal["private"] = "private"
    permitted_uses: list[Literal["context", "discussion", "exploration"]] = Field(
        default_factory=lambda: ["context"],
        min_length=1,
        max_length=3,
    )
    valid_from: str = ""
    valid_to: str = ""
    expires_at: str = ""
    source_agent: Literal["BooksAgent"] = "BooksAgent"

    @model_validator(mode="after")
    def enforce_proposal_boundary(self) -> Self:
        if self.wisdom_type == "situational_connection" and not (
            self.valid_to or self.expires_at
        ):
            raise ValueError("situational Book Wisdom requires a time bound")
        return self


class BooksAgentEnvelope(BooksContractModel):
    schema_version: Literal["books-agent-response-v1"] = "books-agent-response-v1"
    answer: str = Field(min_length=1)
    answer_claim_ids: list[str] = Field(default_factory=list)
    claims: list[BookClaim] = Field(default_factory=list)
    evidence: list[BookEvidenceAnchor] = Field(default_factory=list)
    judgment: BookJudgment | None = None
    retrieval_policy: BookRetrievalPolicy | None = None
    user_learning_events: list[UserLearningEvent] = Field(default_factory=list)
    wisdom_proposals: list[BookWisdomProposal] = Field(default_factory=list, max_length=1)
    uncertainty: list[str] = Field(default_factory=list)
    status: Literal["complete", "partial", "abstained", "failed"]

    @model_validator(mode="after")
    def validate_evidence_graph(self) -> Self:
        claim_by_id = _unique_by_id(self.claims, "claim")
        evidence_by_id = _unique_by_id(self.evidence, "evidence")
        learning_by_id = _unique_by_id(self.user_learning_events, "user learning event")
        _unique_by_id(self.wisdom_proposals, "Wisdom proposal")
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
        for proposal in self.wisdom_proposals:
            event = learning_by_id.get(proposal.user_learning_event_id)
            if event is None:
                raise ValueError(
                    "Wisdom user_learning_event_id must reference an event in this envelope"
                )
            if "wisdom" not in event.permitted_uses:
                raise ValueError("Wisdom user-learning event must permit wisdom use")
            referenced = set(proposal.evidence_ids) | set(proposal.conflicting_evidence_ids)
            if referenced - set(evidence_by_id):
                raise ValueError("Wisdom evidence_ids must reference evidence in this envelope")
            if any(not evidence_by_id[evidence_id].validated for evidence_id in referenced):
                raise ValueError("Wisdom evidence_ids must reference validated Book evidence")
            if not set(proposal.evidence_ids).intersection(event.evidence_ids):
                raise ValueError("Wisdom must share supporting evidence with its user-learning event")
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
