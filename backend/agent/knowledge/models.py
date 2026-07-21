"""Stable data contracts for Vellum's Personal Intelligence layer."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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
    vault_library: bool = True
    knowledge_wiki: bool = True
    agent_projections: bool = True
    apply: bool = False
    confirm: bool = False
    limit: int | None = Field(default=None, ge=1, le=100000)
