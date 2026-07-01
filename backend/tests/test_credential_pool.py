from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from agent.llm.routing.models import (
    CredentialRecord,
    CredentialStatus,
    CredentialStrategy,
)
from agent.llm.routing.pool import CredentialPool
from agent.llm.routing.store import RoutingStore


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, **kwargs: int) -> None:
        self.current += timedelta(**kwargs)


def add_credential(
    store: RoutingStore,
    label: str,
    *,
    models: list[str] | None = None,
) -> CredentialRecord:
    return store.upsert_credential(
        CredentialRecord(
            provider="openrouter",
            label=label,
            source=f"keyring:{label}",
            fingerprint=f"fp:{label}",
            model_allowlist=models or [],
        )
    )


def test_round_robin_skips_cooling_and_model_ineligible_credentials(tmp_path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        store = RoutingStore(tmp_path / "routing.db")
        first = add_credential(store, "one", models=["google/model"])
        second = add_credential(store, "two", models=["other/model"])
        third = add_credential(store, "three")
        pool = CredentialPool(store, clock=clock.now)
        pool.set_strategy("openrouter", CredentialStrategy.round_robin)
        store.set_credential_state(
            second.id,
            status=CredentialStatus.cooldown,
            cooldown_until=clock.now() + timedelta(hours=1),
            consecutive_429=2,
        )

        lease_one = await pool.lease("openrouter", "google/model")
        await pool.release(lease_one)
        lease_two = await pool.lease("openrouter", "google/model")

        assert lease_one.credential_id == first.id
        assert lease_two.credential_id == third.id

    asyncio.run(scenario())


def test_second_generic_429_rotates_and_success_resets_state(tmp_path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        store = RoutingStore(tmp_path / "routing.db")
        credential = add_credential(store, "one")
        add_credential(store, "two")
        pool = CredentialPool(store, clock=clock.now)

        first_lease = await pool.lease("openrouter", "google/model")
        assert await pool.mark_generic_429(first_lease) is False
        second_lease = await pool.lease("openrouter", "google/model", preferred_id=credential.id)
        assert await pool.mark_generic_429(second_lease) is True

        cooled = store.get_credential(credential.id)
        assert cooled is not None
        assert cooled.status is CredentialStatus.cooldown
        assert cooled.cooldown_until == clock.now() + timedelta(hours=1)

        replacement = await pool.lease("openrouter", "google/model")
        assert replacement.credential_id != credential.id
        await pool.mark_success(replacement)
        healthy = store.get_credential(replacement.credential_id)
        assert healthy is not None
        assert healthy.status is CredentialStatus.healthy
        assert healthy.consecutive_429 == 0

    asyncio.run(scenario())


def test_auth_and_billing_failures_apply_distinct_states(tmp_path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        store = RoutingStore(tmp_path / "routing.db")
        auth = add_credential(store, "auth")
        billing = add_credential(store, "billing")
        pool = CredentialPool(store, clock=clock.now)

        auth_lease = await pool.lease("openrouter", "model", preferred_id=auth.id)
        await pool.mark_auth_invalid(auth_lease)
        billing_lease = await pool.lease("openrouter", "model", preferred_id=billing.id)
        await pool.mark_billing_exhausted(billing_lease)

        assert store.get_credential(auth.id).status is CredentialStatus.invalid
        billed = store.get_credential(billing.id)
        assert billed.status is CredentialStatus.cooldown
        assert billed.cooldown_until == clock.now() + timedelta(hours=24)

    asyncio.run(scenario())


def test_expired_cooldown_and_lease_are_reaped_lazily(tmp_path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        store = RoutingStore(tmp_path / "routing.db")
        credential = add_credential(store, "one")
        pool = CredentialPool(store, clock=clock.now, lease_ttl=timedelta(seconds=30))
        store.set_credential_state(
            credential.id,
            status=CredentialStatus.cooldown,
            cooldown_until=clock.now() + timedelta(seconds=10),
            consecutive_429=2,
        )
        clock.advance(seconds=11)

        lease = await pool.lease("openrouter", "model")
        clock.advance(seconds=31)
        assert pool.reap_expired_leases() == 1
        refreshed = store.get_credential(credential.id)
        assert refreshed.status is CredentialStatus.healthy
        assert lease.credential_id == credential.id

    asyncio.run(scenario())
