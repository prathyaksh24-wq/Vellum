from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
import asyncio
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from agent.llm.routing.adapters import classify_provider_exception
from agent.llm.routing.models import (
    CredentialRecord,
    FailureKind,
    FallbackTarget,
    ProviderFailure,
    RoutingTerminalError,
    merge_policy,
)
from agent.llm.routing.pool import CredentialPool, CredentialPoolExhausted
from agent.llm.routing.store import RoutingStore


class SecretResolverProtocol(Protocol):
    def resolve(self, credential: CredentialRecord) -> str: ...


class ProviderAdapterProtocol(Protocol):
    def build_model(self, **kwargs: Any): ...


@dataclass(frozen=True)
class AttemptPlan:
    correlation_id: str
    targets: tuple[FallbackTarget, ...]


class RoutingEngine:
    def __init__(
        self,
        *,
        store: RoutingStore,
        pool: CredentialPool,
        secret_resolver: SecretResolverProtocol,
        adapters: dict[str, ProviderAdapterProtocol],
        max_targets: int = 4,
        max_transient_retries: int = 2,
        async_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = lambda: 0.0,
    ) -> None:
        self.store = store
        self.pool = pool
        self.secret_resolver = secret_resolver
        self.adapters = adapters
        self.max_targets = max_targets
        self.max_transient_retries = max_transient_retries
        self.async_sleep = async_sleep
        self.jitter = jitter

    def _primary_provider(self, model: str) -> str:
        if model.startswith("openai/"):
            native = self.store.list_credentials("openai")
            if any(item.status.value == "healthy" for item in native):
                return "openai"
        return "openrouter"

    def build_plan(self, primary_model: str, primary_provider: str | None = None) -> AttemptPlan:
        primary = FallbackTarget(
            provider=primary_provider or self._primary_provider(primary_model),
            model=primary_model,
        )
        targets = [primary]
        for fallback in self.store.list_fallbacks():
            if fallback.identity != primary.identity:
                targets.append(fallback)
        return AttemptPlan(
            correlation_id=f"route-{uuid4().hex}",
            targets=tuple(targets[: self.max_targets]),
        )

    async def ainvoke(
        self,
        *,
        messages: Sequence[Any],
        primary_model: str,
        primary_provider: str | None = None,
        tools: Sequence[Any] = (),
        temperature: float = 0.3,
        max_tokens: int = 2048,
        thread_id: str = "background",
        **kwargs: Any,
    ):
        del thread_id  # reserved for content-free attempt telemetry
        plan = self.build_plan(primary_model, primary_provider)
        failures: list[ProviderFailure] = []

        for target in plan.targets:
            adapter = self.adapters.get(target.provider)
            if adapter is None:
                failures.append(
                    ProviderFailure(
                        kind=FailureKind.model_unavailable,
                        summary="provider adapter is unavailable",
                    )
                )
                continue

            preferred_id: str | None = None
            transient_retries = 0
            malformed_retries = 0

            while True:
                try:
                    lease = await self.pool.lease(
                        target.provider,
                        target.model,
                        preferred_id=preferred_id,
                    )
                except CredentialPoolExhausted:
                    failures.append(
                        ProviderFailure(
                            kind=FailureKind.auth,
                            summary="no healthy provider credentials",
                        )
                    )
                    break

                credential = self.store.get_credential(lease.credential_id)
                if credential is None:
                    await self.pool.release(lease)
                    failures.append(
                        ProviderFailure(
                            kind=FailureKind.auth,
                            summary="credential metadata is unavailable",
                        )
                    )
                    break

                try:
                    secret = self.secret_resolver.resolve(credential)
                    policy = None
                    if target.provider == "openrouter":
                        policy = merge_policy(
                            self.store.get_global_policy(),
                            self.store.get_model_policy(target.model),
                        )
                    model = adapter.build_model(
                        target=target,
                        secret=secret,
                        temperature=temperature,
                        policy=policy,
                        max_tokens=max_tokens,
                    )
                    if tools:
                        model = model.bind_tools(list(tools))
                    result = await model.ainvoke(list(messages), **kwargs)
                    has_content = bool(getattr(result, "content", None))
                    has_tool_calls = bool(getattr(result, "tool_calls", None))
                    if not has_content and not has_tool_calls:
                        failure = ProviderFailure(
                            kind=FailureKind.malformed_response,
                            summary="provider returned an invalid response",
                        )
                    else:
                        await self.pool.mark_success(lease)
                        return result
                except Exception as exc:
                    failure = classify_provider_exception(exc)

                failures.append(failure)

                if failure.kind is FailureKind.auth:
                    await self.pool.mark_auth_invalid(lease)
                    preferred_id = None
                    continue
                if failure.kind in {FailureKind.billing, FailureKind.plan_exhausted}:
                    await self.pool.mark_billing_exhausted(lease)
                    preferred_id = None
                    continue
                if failure.kind is FailureKind.rate_limit:
                    rotate = await self.pool.mark_generic_429(lease)
                    preferred_id = None if rotate else credential.id
                    delay = failure.retry_after_seconds or 0.0
                    if not rotate and delay:
                        await self.async_sleep(delay)
                    continue
                if failure.kind is FailureKind.model_unavailable:
                    await self.pool.release(lease)
                    break
                if failure.kind is FailureKind.invalid_request:
                    await self.pool.release(lease)
                    raise RoutingTerminalError(
                        correlation_id=plan.correlation_id,
                        failures=failures,
                    )
                if failure.kind is FailureKind.malformed_response:
                    await self.pool.release(lease)
                    if malformed_retries < 1:
                        malformed_retries += 1
                        preferred_id = credential.id
                        continue
                    break
                if failure.kind in {FailureKind.timeout, FailureKind.network, FailureKind.server}:
                    await self.pool.release(lease)
                    if transient_retries < self.max_transient_retries:
                        delay = failure.retry_after_seconds
                        if delay is None:
                            delay = min(8.0, (2**transient_retries) + self.jitter())
                        transient_retries += 1
                        preferred_id = credential.id
                        await self.async_sleep(delay)
                        continue
                    break

                await self.pool.release(lease)
                break

        raise RoutingTerminalError(
            correlation_id=plan.correlation_id,
            failures=failures,
        )
