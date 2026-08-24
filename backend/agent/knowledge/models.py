"""Stable data contracts for Vellum's Personal Intelligence layer."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class BookImportRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=160)
    rights_attestation_version: str = Field(min_length=1, max_length=120)
    scan_approved: Literal[True]
    pipeline_version: str = Field(default="book-epub-intake-v1", min_length=1, max_length=120)
    requested_by: str = Field(default="user", min_length=1, max_length=120)

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


class BookStageReceipt(BaseModel):
    id: str
    stage: Literal[
        "received",
        "quarantined",
        "validated",
        "extracted",
        "identified",
        "structured",
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
    status: Literal[
        "received",
        "quarantined",
        "validated",
        "extracted",
        "identified",
        "structured",
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
