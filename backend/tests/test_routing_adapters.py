from __future__ import annotations

import httpx
import pytest

from agent.llm.routing.adapters import (
    OpenAIAdapter,
    OpenRouterAdapter,
    classify_provider_exception,
)
from agent.llm.routing.models import FailureKind, FallbackTarget, ProviderRoutingPolicy


class FakeStatusError(RuntimeError):
    def __init__(self, status_code: int, message: str, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = type(
            "Response",
            (),
            {"status_code": status_code, "headers": {"Retry-After": retry_after} if retry_after else {}},
        )()


def test_openrouter_adapter_builds_effective_provider_body() -> None:
    adapter = OpenRouterAdapter(base_url="https://openrouter.ai/api/v1")
    model = adapter.build_model(
        target=FallbackTarget(provider="openrouter", model="google/test"),
        secret="key",
        temperature=0.2,
        policy=ProviderRoutingPolicy(
            sort="price",
            ignore=["Together"],
            require_parameters=True,
        ),
    )

    assert model.model_name == "google/test"
    assert model.openai_api_base == "https://openrouter.ai/api/v1"
    assert model.extra_body["provider"] == {
        "sort": "price",
        "ignore": ["Together"],
        "require_parameters": True,
        "data_collection": "deny",
        "zdr": True,
    }


def test_openai_adapter_strips_vendor_prefix_and_has_no_openrouter_body() -> None:
    model = OpenAIAdapter(base_url="https://api.openai.com/v1").build_model(
        target=FallbackTarget(provider="openai", model="openai/gpt-test"),
        secret="key",
        temperature=0.3,
        policy=None,
    )

    assert model.model_name == "gpt-test"
    assert not model.extra_body


@pytest.mark.parametrize(
    ("status", "message", "kind"),
    [
        (401, "expired", FailureKind.auth),
        (403, "forbidden", FailureKind.auth),
        (402, "credits exhausted", FailureKind.billing),
        (404, "model not found", FailureKind.model_unavailable),
        (429, "daily quota exceeded", FailureKind.plan_exhausted),
        (429, "rate limited", FailureKind.rate_limit),
        (503, "overloaded", FailureKind.server),
        (400, "bad parameter", FailureKind.invalid_request),
    ],
)
def test_error_classifier(status: int, message: str, kind: FailureKind) -> None:
    failure = classify_provider_exception(FakeStatusError(status, message))

    assert failure.kind is kind
    assert failure.status_code == status


def test_classifier_honors_retry_after_and_sanitizes_secret_like_text() -> None:
    failure = classify_provider_exception(
        FakeStatusError(429, "Bearer sk-secret-value was rejected", retry_after="7")
    )

    assert failure.retry_after_seconds == 7
    assert "sk-secret-value" not in failure.summary
    assert "Bearer" not in failure.summary


def test_network_and_timeout_exceptions_are_distinct() -> None:
    request = httpx.Request("POST", "https://example.test")

    assert classify_provider_exception(httpx.ReadTimeout("slow", request=request)).kind is FailureKind.timeout
    assert classify_provider_exception(httpx.ConnectError("offline", request=request)).kind is FailureKind.network
