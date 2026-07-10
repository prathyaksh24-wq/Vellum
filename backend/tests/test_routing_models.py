from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.llm.routing.models import (
    CredentialRecord,
    CredentialStatus,
    CredentialStrategy,
    FailureKind,
    FallbackTarget,
    ProviderFailure,
    ProviderRoutingPolicy,
    RoutingTerminalError,
    validate_fallback_chain,
    merge_policy,
)


def test_model_policy_replaces_global_lists_and_keeps_privacy_floor() -> None:
    global_policy = ProviderRoutingPolicy(
        sort="latency",
        order=["Fireworks", "DeepInfra"],
        require_parameters=True,
        data_collection="deny",
        zdr=True,
    )
    override = ProviderRoutingPolicy(sort="price", order=["Together"])

    merged = merge_policy(global_policy, override)

    assert merged.sort == "price"
    assert merged.order == ["Together"]
    assert merged.require_parameters is True
    assert merged.data_collection == "deny"
    assert merged.zdr is True


def test_policy_rejects_provider_in_only_and_ignore() -> None:
    with pytest.raises(ValidationError, match="both only and ignore"):
        ProviderRoutingPolicy(only=["Fireworks"], ignore=["fireworks"])


def test_policy_rejects_order_outside_only() -> None:
    with pytest.raises(ValidationError, match="order entries must appear in only"):
        ProviderRoutingPolicy(only=["Fireworks"], order=["DeepInfra"])


def test_openrouter_body_omits_unset_and_empty_optional_values() -> None:
    policy = ProviderRoutingPolicy(sort="latency", only=[], ignore=None)

    assert policy.to_openrouter_body() == {
        "sort": "latency",
        "order": ["Fireworks", "Together", "DeepInfra"],
        "data_collection": "deny",
        "zdr": True,
    }


def test_fallback_requires_supported_provider_and_model() -> None:
    target = FallbackTarget(provider="openrouter", model="qwen/qwen3.5-35b-a3b")
    assert target.provider == "openrouter"

    with pytest.raises(ValidationError):
        FallbackTarget(provider="anthropic", model="claude")
    with pytest.raises(ValidationError):
        FallbackTarget(provider="openrouter", model="   ")


def test_fallback_chain_rejects_duplicates_and_primary_target() -> None:
    first = FallbackTarget(provider="openrouter", model="qwen/fallback")
    duplicate = FallbackTarget(provider="openrouter", model="QWEN/FALLBACK")

    with pytest.raises(ValueError, match="duplicate fallback target"):
        validate_fallback_chain([first, duplicate])

    with pytest.raises(ValueError, match="matches the primary target"):
        validate_fallback_chain(
            [first],
            primary=FallbackTarget(provider="openrouter", model="qwen/fallback"),
        )


def test_credential_record_contains_reference_metadata_not_a_secret() -> None:
    credential = CredentialRecord(
        provider="openrouter",
        label="primary",
        source="env:OPENROUTER_API_KEY",
        fingerprint="sha256:abc123",
        strategy=CredentialStrategy.round_robin,
    )

    assert credential.status is CredentialStatus.healthy
    assert "secret" not in credential.model_dump()
    assert "api_key" not in credential.model_dump()


def test_terminal_error_exposes_only_normalized_failure_summaries() -> None:
    failure = ProviderFailure(
        kind=FailureKind.auth,
        summary="authentication failed",
        status_code=401,
    )

    error = RoutingTerminalError(correlation_id="route-123", failures=[failure])

    assert "route-123" in str(error)
    assert "authentication failed" in str(error)
    assert error.correlation_id == "route-123"
