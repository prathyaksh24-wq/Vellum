from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent.llm.routing.models import (
    CredentialRecord,
    CredentialStatus,
    FallbackTarget,
    ProviderRoutingPolicy,
    RoutingAttempt,
)
from agent.llm.routing.store import RoutingStore


def test_policy_fallback_and_cooldown_survive_store_reopen(tmp_path) -> None:
    path = tmp_path / "routing.db"
    store = RoutingStore(path)
    store.set_global_policy(ProviderRoutingPolicy(sort="price", require_parameters=True))
    store.set_model_policy("google/model", ProviderRoutingPolicy(order=["Fireworks"]))
    store.replace_fallbacks(
        [FallbackTarget(provider="openrouter", model="qwen/test")]
    )
    credential = store.upsert_credential(
        CredentialRecord(
            provider="openrouter",
            label="primary",
            source="env:OPENROUTER_API_KEY",
            fingerprint="sha256:fp1",
        )
    )
    cooldown = datetime(2030, 1, 1, tzinfo=UTC)
    store.set_credential_state(
        credential.id,
        status=CredentialStatus.cooldown,
        cooldown_until=cooldown,
        consecutive_429=2,
    )

    reopened = RoutingStore(path)

    assert reopened.get_global_policy().sort == "price"
    assert reopened.get_global_policy().require_parameters is True
    assert reopened.get_model_policy("google/model").order == ["Fireworks"]
    assert reopened.list_fallbacks()[0].model == "qwen/test"
    saved = reopened.get_credential(credential.id)
    assert saved is not None
    assert saved.status is CredentialStatus.cooldown
    assert saved.cooldown_until == cooldown
    assert saved.consecutive_429 == 2


def test_invalid_fallback_replacement_does_not_destroy_existing_chain(tmp_path) -> None:
    store = RoutingStore(tmp_path / "routing.db")
    store.replace_fallbacks(
        [FallbackTarget(provider="openrouter", model="one/model")]
    )

    with pytest.raises(ValueError, match="duplicate fallback target"):
        store.replace_fallbacks(
            [
                FallbackTarget(provider="openrouter", model="dup/model"),
                FallbackTarget(provider="openrouter", model="DUP/MODEL"),
            ]
        )

    assert [item.model for item in store.list_fallbacks()] == ["one/model"]


def test_upsert_by_source_updates_metadata_without_creating_duplicate(tmp_path) -> None:
    store = RoutingStore(tmp_path / "routing.db")
    first = store.upsert_credential(
        CredentialRecord(
            provider="openrouter",
            label="old label",
            source="env:OPENROUTER_API_KEY",
            fingerprint="sha256:old",
        )
    )
    updated = store.upsert_credential(
        CredentialRecord(
            provider="openrouter",
            label="new label",
            source="env:OPENROUTER_API_KEY",
            fingerprint="sha256:new",
        )
    )

    assert updated.id == first.id
    assert updated.label == "new label"
    assert updated.fingerprint == "sha256:new"
    assert len(store.list_credentials("openrouter")) == 1


def test_store_uses_schema_version_one_and_wal(tmp_path) -> None:
    store = RoutingStore(tmp_path / "routing.db")

    assert store.user_version() == 1
    assert store.journal_mode().casefold() == "wal"


def test_content_free_routing_attempts_are_persisted_and_paginated(tmp_path) -> None:
    store = RoutingStore(tmp_path / "routing.db")
    store.record_attempt(
        RoutingAttempt(
            correlation_id="route-1",
            thread_id="thread-1",
            model="google/model",
            api_provider="openrouter",
            credential_fingerprint="hmac:abc",
            attempt_number=1,
            fallback_index=0,
            outcome="success",
            latency_ms=12.5,
        )
    )

    rows = store.list_attempts(limit=10, offset=0)

    assert len(rows) == 1
    assert rows[0].correlation_id == "route-1"
    assert rows[0].credential_fingerprint == "hmac:abc"
    assert "prompt" not in rows[0].model_dump()
    assert "response" not in rows[0].model_dump()
