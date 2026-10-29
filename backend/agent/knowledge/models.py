"""Stable data contracts for Vellum's Personal Intelligence layer."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Sensitivity(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    PRIVATE_LOCAL_ONLY = "private_local_only"


class ExternalPolicy(str, Enum):
    ALLOW = "allow"
    ALLOW_SCRUBBED = "allow_scrubbed"
    DENY_RAW = "deny_raw"


class ObservationActor(str, Enum):
    USER = "user"
    AGENT = "agent"
    SCHEDULED = "scheduled"
    CONNECTOR = "connector"
    IMPORTED = "imported"


class PromotionStatus(str, Enum):
    EPHEMERAL = "ephemeral"
    CANDIDATE = "candidate"
    DURABLE = "durable"
    REJECTED = "rejected"


class EvidenceClass(str, Enum):
    EXPLICIT = "explicit"
    ENGAGEMENT = "engagement"
    PASSIVE = "passive"
    IMPORTED = "imported"


class UserLearningSensitivity(str, Enum):
    PRIVATE = "private"
    SENSITIVE = "sensitive"


class IngestionJobStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ContentStance(str, Enum):
    UNKNOWN = "unknown"
    SUPPORT = "support"
    CRITICISM = "criticism"
    SATIRE = "satire"
    QUOTATION = "quotation"
    MIXED = "mixed"


class SourceItemInput(BaseModel):
    kind: str = Field(min_length=1, max_length=80)
    external_id: str = Field(min_length=1, max_length=500)
    title: str = Field(default="", max_length=500)
    content: str | None = None
    uri: str = Field(default="", max_length=2000)
    source_path: str = Field(default="", max_length=2000)
    account_id: str = Field(default="", max_length=500)
    published_at: datetime | None = None
    observed_at: datetime | None = None
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    external_policy: ExternalPolicy = ExternalPolicy.ALLOW_SCRUBBED
    trust: str = Field(default="unknown", max_length=80)
    status: str = Field(default="active", max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind", "external_id")
    @classmethod
    def clean_identity(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("identity fields cannot be blank")
        return clean


class EntityIdentityInput(BaseModel):
    entity_type: str = Field(min_length=1, max_length=80)
    external_id: str = Field(min_length=1, max_length=500)
    canonical_name: str = Field(min_length=1, max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=500)
    source_id: str | None = None
    observed_at: datetime | None = None
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entity_type", "external_id", "canonical_name")
    @classmethod
    def clean_entity_identity(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("entity identity fields cannot be blank")
        return clean

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, aliases: list[str]) -> list[str]:
        return list(dict.fromkeys(alias.strip() for alias in aliases if alias.strip()))


class ObservationInput(BaseModel):
    origin: str = Field(min_length=1, max_length=120)
    action: str = Field(min_length=1, max_length=160)
    actor: ObservationActor
    trigger: str = Field(default="", max_length=160)
    source_id: str | None = None
    event_key: str = Field(default="", max_length=500)
    payload: dict[str, Any] = Field(default_factory=dict)
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    observed_at: datetime | None = None
    expires_at: datetime | None = None
    promotion_status: PromotionStatus = PromotionStatus.EPHEMERAL


class ProjectionInput(BaseModel):
    canonical_type: str = Field(min_length=1, max_length=80)
    canonical_id: str = Field(min_length=1, max_length=160)
    target: str = Field(min_length=1, max_length=80)
    target_ref: str = Field(min_length=1, max_length=2000)
    content_hash: str = Field(default="", max_length=128)
    projection_type: str = Field(default="readable", max_length=80)
    generated_by: str = Field(default="vellum", max_length=80)
    do_not_reingest: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserSignalInput(BaseModel):
    subject_key: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1, max_length=120)
    signal_type: str = Field(min_length=1, max_length=120)
    event_key: str = Field(min_length=1, max_length=500)
    value: float = Field(ge=-1.0, le=1.0)
    weight: float = Field(default=1.0, gt=0.0, le=10.0)
    actor: ObservationActor
    evidence_class: EvidenceClass = EvidenceClass.ENGAGEMENT
    preference_evidence: bool = True
    source_id: str | None = None
    observation_id: str | None = None
    observed_at: datetime | None = None
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("subject_key", "category", "signal_type", "event_key")
    @classmethod
    def clean_signal_identity(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("signal identity fields cannot be blank")
        return clean


class IngestionJobInput(BaseModel):
    connector: str = Field(min_length=1, max_length=120)
    account_id: str = Field(min_length=1, max_length=500)
    job_type: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=500)
    requested_by: str = Field(min_length=1, max_length=120)
    lease_seconds: int = Field(default=900, ge=30, le=86400)


class BookDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    user_id: str = Field(min_length=1, max_length=160)
    objective: Literal["user_discovery", "vellum_exploration"]
    query: str = Field(min_length=1, max_length=300)
    request_key: str = Field(min_length=1, max_length=160)
    max_candidates: int = Field(default=6, ge=1, le=20)


class BookDiscoveryVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    user_id: str = Field(min_length=1, max_length=160)
    candidate_id: str = Field(
        min_length=47,
        max_length=47,
        pattern=r"^book-discovery_[0-9a-f]{32}$",
    )
    request_key: str = Field(min_length=1, max_length=160)

    @field_validator("user_id", "request_key")
    @classmethod
    def clean_verification_identity(cls, value: str) -> str:
        clean = value.strip()
        if not clean or any(ord(character) < 32 for character in clean):
            raise ValueError("verification identity fields cannot be blank or contain controls")
        return clean


class BookDiscoveryPolicy(BaseModel):
    """Host-supplied authority, never populated from model/tool arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    network_allowed: bool = False
    public_query_approved: bool = False
    local_only: bool = False
    max_response_bytes: int = Field(default=262144, ge=1024, le=1048576)
    max_retained_candidates: int = Field(default=200, ge=1, le=1000)
    deadline_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    candidate_ttl_days: int = Field(default=30, ge=1, le=90)


class BookImportRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=160)
    rights_attestation_version: str = Field(min_length=1, max_length=120)
    scan_approved: Literal[True]
    pipeline_version: str = Field(default="book-epub-intake-v1", min_length=1, max_length=120)
    requested_by: str = Field(default="user", min_length=1, max_length=120)
    local_only: bool = False

    @field_validator("user_id", "rights_attestation_version", "pipeline_version", "requested_by")
    @classmethod
    def clean_book_import_identity(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("book import identity fields cannot be blank")
        return clean


class BookDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=160)
    import_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=160)

    @field_validator("user_id", "import_id", "run_id")
    @classmethod
    def clean_book_document_identity(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("book document identity fields cannot be blank")
        return clean


class BookQualityRequest(BookDocumentRequest):
    document_id: str = Field(min_length=1, max_length=160)

    @field_validator("document_id")
    @classmethod
    def clean_book_quality_document_id(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("book quality document id cannot be blank")
        return clean


class BookMaterializationRequest(BookQualityRequest):
    pass


class BookRetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=160)
    query: str = Field(min_length=1, max_length=8000)
    destination: Literal["local", "external"] = "local"
    max_chunks: int = Field(default=6, ge=1, le=12)
    token_budget: int = Field(default=2400, ge=256, le=8000)

    @field_validator("user_id", "query")
    @classmethod
    def clean_book_retrieval_text(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("book retrieval fields cannot be blank")
        return clean


class BookRelationshipEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=160)
    event_key: str = Field(min_length=1, max_length=500)
    action: Literal[
        "book.imported",
        "book.discovered",
        "book.processed",
        "book.summarized",
        "book.questioned",
        "book.returned",
        "citation.inspected",
        "idea.discussed",
        "idea.compared",
        "idea.challenged",
        "idea.applied",
        "idea.connected",
        "interface.page_flipped",
        "user.statement_recorded",
        "reading_status.stated",
        "reading_status.connector_observed",
    ]
    actor: ObservationActor
    evidence_basis: Literal["explicit", "interaction", "imported", "agent_activity", "connector"]
    trigger: str = Field(default="books_agent", max_length=160)
    book_ids: list[str] = Field(default_factory=list, max_length=50)
    source_anchor_ids: list[str] = Field(default_factory=list, max_length=100)
    conversation_ids: list[str] = Field(default_factory=list, max_length=100)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    observed_at: datetime | None = None
    sensitivity: Sensitivity = Sensitivity.PRIVATE_LOCAL_ONLY

    @field_validator("user_id", "event_key")
    @classmethod
    def clean_relationship_identity(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Book relationship identity fields cannot be blank")
        return clean

    @field_validator("book_ids", "source_anchor_ids", "conversation_ids")
    @classmethod
    def clean_relationship_references(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class BookUserLearningEvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["observation", "book", "book_anchor", "conversation"]
    reference_id: str = Field(min_length=1, max_length=500)
    stance: Literal["supports", "conflicts"] = "supports"

    @field_validator("reference_id")
    @classmethod
    def clean_learning_reference(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("User-learning evidence reference cannot be blank")
        return clean


class BookUserLearningCandidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=160)
    proposition_type: Literal[
        "taste",
        "preference",
        "principle",
        "belief",
        "struggle",
        "goal",
        "emotional_state",
        "current_situation",
        "practical_need",
        "reading_status",
        "reaction",
        "book_impact",
        "changing_interest",
        "contradiction",
    ]
    proposition: str = Field(min_length=1, max_length=8000)
    basis: Literal["explicit", "inferred"]
    actor: ObservationActor
    evidence: list[BookUserLearningEvidenceReference] = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)
    sensitivity: UserLearningSensitivity = UserLearningSensitivity.PRIVATE
    scope: str = Field(default="books", min_length=1, max_length=120)
    permitted_uses: list[Literal["context", "personalization", "wisdom"]] = Field(
        default_factory=lambda: ["context"],
        min_length=1,
        max_length=3,
    )
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    expires_at: datetime | None = None
    derivation: str = Field(min_length=1, max_length=160)
    model_version: str = Field(default="", max_length=160)
    prompt_version: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=160)
    schema_version: Literal["book-user-learning-v1"] = "book-user-learning-v1"
    source_agent: str = Field(default="BooksAgent", min_length=1, max_length=160)

    @field_validator(
        "user_id",
        "proposition",
        "scope",
        "derivation",
        "prompt_version",
        "policy_version",
        "source_agent",
    )
    @classmethod
    def clean_learning_text(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("User-learning fields cannot be blank")
        return clean

    @field_validator("permitted_uses")
    @classmethod
    def clean_permitted_uses(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def enforce_sensitive_learning_boundary(self) -> "BookUserLearningCandidateInput":
        if self.sensitivity == UserLearningSensitivity.SENSITIVE and (
            self.basis != "explicit" or self.actor != ObservationActor.USER
        ):
            raise ValueError("Sensitive learning requires explicit user evidence")
        if not any(item.stance == "supports" for item in self.evidence):
            raise ValueError("User-learning candidates require supporting evidence")
        if self.proposition_type in {"emotional_state", "current_situation"} and not (
            self.valid_to or self.expires_at
        ):
            raise ValueError("Temporary user learning requires a time bound")
        return self


class BookUserLearningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship: BookRelationshipEventInput
    candidates: list[BookUserLearningCandidateInput] = Field(default_factory=list, max_length=20)


class BookWisdomEvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["book", "book_anchor", "user_learning_candidate", "conversation"]
    reference_id: str = Field(min_length=1, max_length=500)
    stance: Literal["supports", "conflicts"] = "supports"

    @field_validator("reference_id")
    @classmethod
    def clean_wisdom_reference(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Wisdom evidence reference cannot be blank")
        return clean


class BookWisdomRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=160)
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
    evidence: list[BookWisdomEvidenceReference] = Field(min_length=2, max_length=300)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: list[str] = Field(default_factory=list, max_length=50)
    sensitivity: UserLearningSensitivity = UserLearningSensitivity.PRIVATE
    permitted_uses: list[Literal["context", "discussion", "exploration"]] = Field(
        default_factory=lambda: ["context"],
        min_length=1,
        max_length=3,
    )
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    expires_at: datetime | None = None
    derivation: str = Field(min_length=1, max_length=160)
    source_agent: str = Field(default="BooksAgent", min_length=1, max_length=160)
    model_version: str = Field(default="", max_length=160)
    prompt_version: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=160)
    schema_version: Literal["book-wisdom-v1"] = "book-wisdom-v1"

    @field_validator(
        "user_id",
        "title",
        "content",
        "author_perspective",
        "user_perspective",
        "vellum_perspective",
        "explanation",
        "derivation",
        "source_agent",
        "prompt_version",
        "policy_version",
    )
    @classmethod
    def clean_wisdom_text(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Book Wisdom fields cannot be blank")
        return clean

    @field_validator("uncertainty")
    @classmethod
    def clean_wisdom_uncertainty(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator("permitted_uses")
    @classmethod
    def clean_wisdom_uses(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def enforce_wisdom_evidence(self) -> "BookWisdomRecordInput":
        supporting_kinds = {
            item.kind
            for item in self.evidence
            if item.stance == "supports"
        }
        if "book_anchor" not in supporting_kinds:
            raise ValueError("Book Wisdom requires supporting Book anchor evidence")
        if "user_learning_candidate" not in supporting_kinds:
            raise ValueError("Book Wisdom requires supporting user-learning evidence")
        if self.wisdom_type == "situational_connection" and not (
            self.valid_to or self.expires_at
        ):
            raise ValueError("Situational Wisdom requires a time bound")
        return self


class BookMaterializationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    materialization_id: str
    edition_id: str
    document_id: str
    document_digest: str
    quality_assessment_id: str
    state: Literal["ready"] = "ready"
    active: bool = True
    skill_id: str
    skill_version: str
    compiler_version: str
    model_version: str
    prompt_version: str
    embedding_model: str
    embedding_model_revision: str = "default"
    policy_snapshot_hash: str
    index_collection: str
    index_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    embedding_count: int = Field(ge=0)


class BookStageReceipt(BaseModel):
    id: str
    stage: Literal[
        "received",
        "quarantined",
        "validated",
        "extracted",
        "identified",
        "structured",
        "skill_compiled",
        "indexed",
        "ready",
    ]
    status: Literal["succeeded", "rejected", "failed_retryable", "failed_permanent"]
    attempt: int = Field(ge=1)
    reason_code: str = ""
    created_at: str


class BookImportStatus(BaseModel):
    import_id: str
    asset_id: str
    run_id: str
    asset_sha256: str
    byte_size: int = Field(ge=0)
    media_type: str
    local_only: bool = False
    status: Literal[
        "received",
        "quarantined",
        "validated",
        "extracted",
        "identified",
        "structured",
        "skill_compiled",
        "indexed",
        "ready",
        "rejected",
        "failed_retryable",
        "failed_permanent",
    ]
    current_stage: Literal[
        "received",
        "quarantined",
        "validated",
        "extracted",
        "identified",
        "structured",
        "skill_compiled",
        "indexed",
        "ready",
    ]
    error_code: str = ""
    document_id: str = ""
    quality_outcome: str = ""
    quality_evaluated: bool = False
    receipts: list[BookStageReceipt] = Field(default_factory=list)


class SyncCursorInput(BaseModel):
    connector: str = Field(min_length=1, max_length=120)
    account_id: str = Field(min_length=1, max_length=500)
    cursor: str = Field(default="", max_length=4000)
    state: dict[str, Any] = Field(default_factory=dict)


class ContentAnnotationInput(BaseModel):
    target_type: Literal["source", "observation", "claim", "insight"]
    target_id: str = Field(min_length=1, max_length=160)
    labels: list[str] = Field(default_factory=list, max_length=50)
    context: str = Field(default="", max_length=160)
    stance: ContentStance = ContentStance.UNKNOWN
    intent: str = Field(default="unknown", max_length=120)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    eligible_for_preference: bool = False
    eligible_for_style: bool = False
    taxonomy_version: str = Field(default="vellum-safety-v1", max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, labels: list[str]) -> list[str]:
        return sorted({label.strip().casefold().replace(" ", "_") for label in labels if label.strip()})


class ContextPackRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    purpose: Literal["chat", "coding", "specialist", "research"] = "chat"
    destination: Literal["local", "external"] = "external"
    token_budget: int = Field(default=4000, ge=256, le=50000)
    source_kinds: list[str] = Field(default_factory=list)
    include_raw_content: bool = False
    citations_required: bool = True


class BootstrapRequest(BaseModel):
    conversations: bool = True
    memories: bool = True
    vault_library: bool = True
    knowledge_wiki: bool = True
    agent_projections: bool = True
    archives: bool = True
    retrieval_indexes: bool = True
    apply: bool = False
    confirm: bool = False
    limit: int | None = Field(default=None, ge=1, le=100000)


class MaterializationCanaryRequest(BaseModel):
    apply: bool = False
    confirmation: str = Field(default="", max_length=80)
