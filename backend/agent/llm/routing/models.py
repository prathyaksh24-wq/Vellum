from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ProviderSort = Literal["price", "latency", "throughput"]
ApiProvider = Literal["openrouter", "openai"]
OPENROUTER_DEFAULT_PROVIDER_ORDER = ("Fireworks", "Together", "DeepInfra")


class CredentialStrategy(StrEnum):
    fill_first = "fill_first"
    round_robin = "round_robin"
    least_used = "least_used"
    random = "random"


class CredentialStatus(StrEnum):
    healthy = "healthy"
    cooldown = "cooldown"
    invalid = "invalid"
    unavailable = "unavailable"


class FailureKind(StrEnum):
    auth = "auth"
    billing = "billing"
    plan_exhausted = "plan_exhausted"
    rate_limit = "rate_limit"
    model_unavailable = "model_unavailable"
    route_unavailable = "route_unavailable"
    timeout = "timeout"
    network = "network"
    server = "server"
    malformed_response = "malformed_response"
    invalid_request = "invalid_request"


def _normalized_names(values: list[str] | None) -> set[str]:
    return {value.casefold() for value in values or []}


class ProviderRoutingPolicy(BaseModel):
    """OpenRouter provider preferences with mandatory Vellum privacy floors."""

    model_config = ConfigDict(extra="forbid")

    sort: ProviderSort | None = None
    only: list[str] | None = None
    ignore: list[str] | None = None
    order: list[str] | None = None
    require_parameters: bool | None = None
    allow_fallbacks: bool | None = None
    data_collection: Literal["deny"] = "deny"
    zdr: Literal[True] = True

    @field_validator("only", "ignore", "order")
    @classmethod
    def normalize_provider_names(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = raw.strip()
            if not value:
                raise ValueError("provider names cannot be empty")
            key = value.casefold()
            if key in seen:
                raise ValueError(f"duplicate provider name: {value}")
            seen.add(key)
            normalized.append(value)
        return normalized

    @model_validator(mode="after")
    def validate_provider_sets(self) -> "ProviderRoutingPolicy":
        only = _normalized_names(self.only)
        ignore = _normalized_names(self.ignore)
        collision = only & ignore
        if collision:
            raise ValueError("a provider cannot appear in both only and ignore")
        order = _normalized_names(self.order)
        if only and not order.issubset(only):
            raise ValueError("order entries must appear in only when only is configured")
        return self

    def to_openrouter_body(self) -> dict[str, object]:
        body: dict[str, object] = {}
        for field in ("sort", "only", "ignore", "order", "require_parameters", "allow_fallbacks"):
            value = getattr(self, field)
            if value is not None and value != []:
                body[field] = value
        body.setdefault("order", list(OPENROUTER_DEFAULT_PROVIDER_ORDER))
        body["data_collection"] = "deny"
        body["zdr"] = True
        return body


class FallbackTarget(BaseModel):
    """A stable cross-model/provider fallback destination."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid4().hex)
    provider: ApiProvider
    model: str = Field(min_length=1)

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model cannot be empty")
        return normalized

    @property
    def identity(self) -> tuple[str, str]:
        return self.provider.casefold(), self.model.casefold()


class CredentialRecord(BaseModel):
    """Persistable credential metadata. Secret-bearing fields are intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid4().hex)
    provider: ApiProvider
    label: str = Field(min_length=1)
    source: str = Field(min_length=1)
    fingerprint: str = Field(min_length=1)
    status: CredentialStatus = CredentialStatus.healthy
    strategy: CredentialStrategy = CredentialStrategy.fill_first
    model_allowlist: list[str] = Field(default_factory=list)
    request_count: int = Field(default=0, ge=0)
    consecutive_429: int = Field(default=0, ge=0)
    cooldown_until: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("label", "source", "fingerprint")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be empty")
        return normalized


class CredentialLease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: uuid4().hex)
    credential_id: str
    provider: ApiProvider
    model: str
    expires_at: datetime


class ProviderFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: FailureKind
    summary: str = Field(min_length=1, max_length=240)
    status_code: int | None = None
    retry_after_seconds: float | None = Field(default=None, ge=0)


class RoutingAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid4().hex)
    correlation_id: str
    thread_id: str
    model: str
    api_provider: ApiProvider
    inference_provider: str | None = None
    credential_fingerprint: str
    attempt_number: int = Field(ge=1)
    fallback_index: int = Field(ge=0)
    outcome: Literal["success", "failure", "interrupted"]
    failure_kind: FailureKind | None = None
    status_code: int | None = None
    latency_ms: float = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RoutingTerminalError(RuntimeError):
    def __init__(self, *, correlation_id: str, failures: list[ProviderFailure]) -> None:
        self.correlation_id = correlation_id
        self.failures = tuple(failures)
        summaries = "; ".join(failure.summary for failure in failures) or "routing failed"
        super().__init__(f"LLM routing failed ({correlation_id}): {summaries}")


class RoutingStreamInterrupted(RuntimeError):
    def __init__(self, *, correlation_id: str, failure: ProviderFailure) -> None:
        self.correlation_id = correlation_id
        self.failure = failure
        super().__init__(f"LLM stream interrupted ({correlation_id}): {failure.summary}")


def merge_policy(
    base: ProviderRoutingPolicy,
    override: ProviderRoutingPolicy | None,
) -> ProviderRoutingPolicy:
    values = base.model_dump()
    if override is not None:
        values.update(override.model_dump(exclude_unset=True))
    values["data_collection"] = "deny"
    values["zdr"] = True
    return ProviderRoutingPolicy(**values)


def validate_fallback_chain(
    targets: list[FallbackTarget],
    *,
    primary: FallbackTarget | None = None,
) -> list[FallbackTarget]:
    seen: set[tuple[str, str]] = set()
    primary_identity = primary.identity if primary is not None else None
    for target in targets:
        if target.identity == primary_identity:
            raise ValueError("fallback target matches the primary target")
        if target.identity in seen:
            raise ValueError("duplicate fallback target")
        seen.add(target.identity)
    return list(targets)
