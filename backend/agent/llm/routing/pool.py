from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import random as random_module

from agent.llm.routing.models import (
    CredentialLease,
    CredentialRecord,
    CredentialStatus,
    CredentialStrategy,
)
from agent.llm.routing.store import RoutingStore


class CredentialPoolExhausted(RuntimeError):
    pass


class CredentialPool:
    def __init__(
        self,
        store: RoutingStore,
        *,
        clock: Callable[[], datetime] | None = None,
        lease_ttl: timedelta = timedelta(minutes=5),
        random_choice: Callable[[list[CredentialRecord]], CredentialRecord] | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))
        self.lease_ttl = lease_ttl
        self.random_choice = random_choice or random_module.choice
        self._lock = asyncio.Lock()

    def set_strategy(self, provider: str, strategy: CredentialStrategy) -> None:
        self.store.set_pool_strategy(provider, strategy)

    def _refresh_expired_cooldowns(self, provider: str) -> None:
        now = self.clock()
        for credential in self.store.list_credentials(provider):
            if (
                credential.status is CredentialStatus.cooldown
                and credential.cooldown_until is not None
                and credential.cooldown_until <= now
            ):
                self.store.set_credential_state(
                    credential.id,
                    status=CredentialStatus.healthy,
                    cooldown_until=None,
                    consecutive_429=0,
                )

    @staticmethod
    def _eligible(credential: CredentialRecord, model: str) -> bool:
        if credential.status is not CredentialStatus.healthy:
            return False
        allowed = {item.casefold() for item in credential.model_allowlist}
        return not allowed or model.casefold() in allowed

    async def lease(
        self,
        provider: str,
        model: str,
        *,
        preferred_id: str | None = None,
    ) -> CredentialLease:
        async with self._lock:
            self._refresh_expired_cooldowns(provider)
            self.store.reap_expired_leases(self.clock())
            candidates = [
                credential
                for credential in self.store.list_credentials(provider)
                if self._eligible(credential, model)
            ]
            if not candidates:
                raise CredentialPoolExhausted(f"no healthy {provider} credentials")

            preferred = next(
                (item for item in candidates if item.id == preferred_id),
                None,
            )
            strategy, cursor = self.store.get_pool_state(provider)
            if preferred is not None:
                selected = preferred
            elif strategy is CredentialStrategy.round_robin:
                selected = candidates[cursor % len(candidates)]
                self.store.set_pool_cursor(provider, cursor + 1)
            elif strategy is CredentialStrategy.least_used:
                selected = min(candidates, key=lambda item: (item.request_count, item.created_at, item.id))
            elif strategy is CredentialStrategy.random:
                selected = self.random_choice(candidates)
            else:
                selected = candidates[0]

            lease = CredentialLease(
                credential_id=selected.id,
                provider=selected.provider,
                model=model,
                expires_at=self.clock() + self.lease_ttl,
            )
            self.store.create_lease(lease)
            self.store.increment_request_count(selected.id)
            return lease

    async def release(self, lease: CredentialLease) -> None:
        self.store.release_lease(lease.id)

    async def mark_success(self, lease: CredentialLease) -> None:
        self.store.set_credential_state(
            lease.credential_id,
            status=CredentialStatus.healthy,
            cooldown_until=None,
            consecutive_429=0,
        )
        await self.release(lease)

    async def mark_generic_429(self, lease: CredentialLease) -> bool:
        credential = self.store.get_credential(lease.credential_id)
        if credential is None:
            await self.release(lease)
            raise KeyError(lease.credential_id)
        consecutive = credential.consecutive_429 + 1
        rotate = consecutive >= 2
        self.store.set_credential_state(
            lease.credential_id,
            status=CredentialStatus.cooldown if rotate else CredentialStatus.healthy,
            cooldown_until=self.clock() + timedelta(hours=1) if rotate else None,
            consecutive_429=consecutive,
        )
        await self.release(lease)
        return rotate

    async def mark_auth_invalid(self, lease: CredentialLease) -> None:
        self.store.set_credential_state(
            lease.credential_id,
            status=CredentialStatus.invalid,
            cooldown_until=None,
            consecutive_429=0,
        )
        await self.release(lease)

    async def mark_billing_exhausted(self, lease: CredentialLease) -> None:
        self.store.set_credential_state(
            lease.credential_id,
            status=CredentialStatus.cooldown,
            cooldown_until=self.clock() + timedelta(hours=24),
            consecutive_429=0,
        )
        await self.release(lease)

    async def mark_plan_exhausted(self, lease: CredentialLease) -> None:
        await self.mark_billing_exhausted(lease)

    def reap_expired_leases(self) -> int:
        return self.store.reap_expired_leases(self.clock())

    def reset_provider(self, provider: str) -> None:
        for credential in self.store.list_credentials(provider):
            if credential.status is not CredentialStatus.invalid:
                self.store.set_credential_state(
                    credential.id,
                    status=CredentialStatus.healthy,
                    cooldown_until=None,
                    consecutive_429=0,
                )
