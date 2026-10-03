from __future__ import annotations

import httpx
import pytest

from agent.llm.routing.adapters import (
    OllamaAdapter,
    OpenAIAdapter,
    OpenRouterAdapter,
    classify_provider_exception,
)
from agent.privacy.disclosure import DisclosureBlocked
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
        "only": ["Fireworks", "DeepInfra"],
        "ignore": ["Together"],
        "order": ["Fireworks", "DeepInfra"],
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


def test_ollama_adapter_strips_local_prefix_and_uses_local_endpoint() -> None:
    model = OllamaAdapter(base_url="http://127.0.0.1:11434/").build_model(
        target=FallbackTarget(provider="ollama", model="ollama/qwen3.5:9b"),
        thread_id="local-chat",
        secret="unused",
        temperature=0.3,
    )

    assert model.model == "qwen3.5:9b"
    assert model.base_url == "http://127.0.0.1:11434"
    assert model.reasoning is False
    assert model.num_ctx == 16384
    assert model.num_batch == 1024


def test_ollama_adapter_respects_configured_batch_size() -> None:
    model = OllamaAdapter(base_url="http://127.0.0.1:11434", batch_size=128).build_model(
        target=FallbackTarget(provider="ollama", model="ollama/gemma4:12b"),
        secret="", temperature=0,
    )
    assert model.num_batch == 128
    from langchain_core.messages import HumanMessage
    params = model._chat_params([HumanMessage(content="Hello")])
    assert params["options"]["num_batch"] == 128
    assert params["options"]["num_ctx"] == 16384
    assert model._chat_params([], options={"num_batch": 64})["options"]["num_batch"] == 64


def test_ollama_adapter_maps_explicit_reasoning_mode() -> None:
    from agent.llm.reasoning import ReasoningMode

    model = OllamaAdapter(base_url="http://127.0.0.1:11434").build_model(
        target=FallbackTarget(provider="ollama", model="ollama/qwen3.5:9b"),
        secret="unused",
        temperature=0.3,
        reasoning_mode=ReasoningMode.high,
    )

    assert model.reasoning is True

def test_ollama_keeps_local_attachment_content_on_device() -> None:
    from langchain_core.messages import HumanMessage
    model = OllamaAdapter(base_url="http://127.0.0.1:11434").build_model(
        target=FallbackTarget(provider="ollama",model="ollama/gemma4:12b"),secret="",temperature=0,
    )
    message=HumanMessage(content=[
        {"type":"text","text":"Read this"},
        {"type":"vellum_attachment_text","name":"Notes.txt","text":"Private local notes","egress_scope":"local_only"},
        {"type":"vellum_attachment_image","data_url":"data:image/png;base64,aGVsbG8="},
    ])
    converted=model._convert_messages_to_ollama_messages([message])
    assert "Private local notes" in converted[0]["content"]
    assert "untrusted data" in converted[0]["content"]
    assert converted[0]["images"] == ["aGVsbG8="]
    assert message.content[1]["type"] == "vellum_attachment_text"


def test_openrouter_adapter_applies_reasoning_mode_body() -> None:
    from agent.llm.reasoning import ReasoningMode

    adapter = OpenRouterAdapter(base_url="https://openrouter.ai/api/v1")
    model = adapter.build_model(
        target=FallbackTarget(provider="openrouter", model="google/test"),
        secret="key",
        temperature=0.2,
        policy=None,
        reasoning_mode=ReasoningMode.high,
    )

    assert model.extra_body["reasoning"] == {"effort": "medium"}


def test_openrouter_adapter_no_reasoning_body_without_mode() -> None:
    adapter = OpenRouterAdapter(base_url="https://openrouter.ai/api/v1")
    model = adapter.build_model(
        target=FallbackTarget(provider="openrouter", model="google/test"),
        secret="key",
        temperature=0.2,
        policy=None,
    )

    assert "reasoning" not in model.extra_body


def test_openai_adapter_applies_reasoning_mode_body() -> None:
    from agent.llm.reasoning import ReasoningMode

    model = OpenAIAdapter(base_url="https://api.openai.com/v1").build_model(
        target=FallbackTarget(provider="openai", model="openai/gpt-test"),
        secret="key",
        temperature=0.3,
        policy=None,
        reasoning_mode=ReasoningMode.ultra,
    )

    assert model.extra_body["reasoning"] == {"effort": "high"}


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


def test_local_disclosure_blocks_fail_fast_as_invalid_request() -> None:
    failure = classify_provider_exception(DisclosureBlocked("model is not approved"))

    assert failure.kind is FailureKind.invalid_request


def test_ollama_translates_json_object_mode_without_mutating_invocation():
    from agent.llm.routing.adapters import OllamaAdapter
    options = {"response_format":{"type":"json_object"}, "num_predict":1000}
    assert OllamaAdapter.invocation_kwargs(options) == {"format":"json", "num_predict":1000}
    assert "response_format" in options
    with pytest.raises(ValueError):
        OllamaAdapter.invocation_kwargs({"response_format":{"type":"unsupported"}})
