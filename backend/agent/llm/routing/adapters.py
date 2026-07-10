from __future__ import annotations

from typing import Any

import httpx

from agent.llm.routing.models import (
    FailureKind,
    FallbackTarget,
    ProviderFailure,
    ProviderRoutingPolicy,
)


_PLAN_EXHAUSTION_PHRASES = (
    "daily quota",
    "daily limit",
    "monthly quota",
    "plan limit",
    "usage limit reached",
    "quota exceeded",
    "quota_exceeded",
    "resource exhausted",
    "resource_exhausted",
    "tokens per day",
)


_FAILURE_SUMMARIES = {
    FailureKind.auth: "provider authentication failed",
    FailureKind.billing: "provider billing quota is exhausted",
    FailureKind.plan_exhausted: "provider usage plan is exhausted",
    FailureKind.rate_limit: "provider rate limit reached",
    FailureKind.model_unavailable: "model route is unavailable",
    FailureKind.route_unavailable: "model route is unavailable",
    FailureKind.timeout: "provider request timed out",
    FailureKind.network: "provider connection failed",
    FailureKind.server: "provider service is unavailable",
    FailureKind.malformed_response: "provider returned an invalid response",
    FailureKind.invalid_request: "provider rejected the request",
}


def _status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _retry_after(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def classify_provider_exception(exc: BaseException) -> ProviderFailure:
    if isinstance(exc, httpx.TimeoutException):
        kind = FailureKind.timeout
        status = None
    elif isinstance(exc, httpx.NetworkError):
        kind = FailureKind.network
        status = None
    else:
        status = _status_code(exc)
        message = str(exc).casefold()[:1000]
        if status in {401, 403}:
            kind = FailureKind.auth
        elif status == 402:
            kind = FailureKind.billing
        elif status == 404 and (
            "no endpoints found" in message
            or "requested parameters" in message
            or "data policy" in message
            or "zero data retention" in message
        ):
            kind = FailureKind.route_unavailable
        elif status == 404:
            kind = FailureKind.model_unavailable
        elif status == 429 and any(phrase in message for phrase in _PLAN_EXHAUSTION_PHRASES):
            kind = FailureKind.plan_exhausted
        elif status == 429:
            kind = FailureKind.rate_limit
        elif status in {408, 409, 425}:
            kind = FailureKind.timeout
        elif status is not None and status >= 500:
            kind = FailureKind.server
        elif status is not None and 400 <= status < 500:
            kind = FailureKind.invalid_request
        else:
            kind = FailureKind.network
    return ProviderFailure(
        kind=kind,
        summary=_FAILURE_SUMMARIES[kind],
        status_code=status,
        retry_after_seconds=_retry_after(exc),
    )


class OpenRouterAdapter:
    provider = "openrouter"

    def __init__(self, *, base_url: str) -> None:
        self.base_url = base_url

    def build_model(
        self,
        *,
        target: FallbackTarget,
        secret: str,
        temperature: float,
        policy: ProviderRoutingPolicy | None,
        max_tokens: int = 2048,
        **kwargs: Any,
    ):
        from langchain_openai import ChatOpenAI

        effective = policy or ProviderRoutingPolicy(
            require_parameters=True,
            allow_fallbacks=True,
        )
        return ChatOpenAI(
            model=target.model,
            api_key=secret,
            base_url=self.base_url,
            temperature=temperature,
            max_tokens=max(256, max_tokens),
            default_headers={
                "HTTP-Referer": "http://localhost",
                "X-Title": "Vellum",
            },
            extra_body={"provider": effective.to_openrouter_body()},
            **kwargs,
        )


class OpenAIAdapter:
    provider = "openai"

    def __init__(self, *, base_url: str) -> None:
        self.base_url = base_url

    def build_model(
        self,
        *,
        target: FallbackTarget,
        secret: str,
        temperature: float,
        policy: ProviderRoutingPolicy | None = None,
        max_tokens: int = 2048,
        **kwargs: Any,
    ):
        from langchain_openai import ChatOpenAI

        model_id = target.model.removeprefix("openai/")
        return ChatOpenAI(
            model=model_id,
            api_key=secret,
            base_url=self.base_url,
            temperature=temperature,
            max_tokens=max(256, max_tokens),
            **kwargs,
        )
