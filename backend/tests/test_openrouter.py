import json
import asyncio

import httpx
import pytest

from agent.graph import agent as react_agent
from agent.llm import openrouter
from agent.privacy.disclosure import (
    DestinationPolicy,
    DisclosureBlocked,
    DisclosureBroker,
    DisclosurePolicy,
    ProtectionMode,
)


def _client_broker(tmp_path):
    settings = openrouter.get_settings()
    return DisclosureBroker(
        policy=DisclosurePolicy(
            mode=ProtectionMode.protect_for_me,
            receipt_path=tmp_path / "privacy-receipts.jsonl",
            destinations={
                "openrouter": DestinationPolicy(
                    name="openrouter",
                    endpoint=settings.openrouter_base_url,
                    approved_models=frozenset(
                        {"test/model", "primary/test", settings.fallback_model}
                    ),
                    data_collection="deny",
                    zdr=True,
                    prompt_logging=False,
                    response_caching=False,
                )
            },
        ),
        alias_key=b"test-client-broker",
    )


def test_openrouter_payload_enforces_privacy_policy():
    payload = openrouter._build_payload(
        system="system",
        user="user",
        model="test/model",
        max_tokens=128,
        temperature=0.2,
        session_id="thread-1",
    )

    reviewed_providers = list(openrouter.get_settings().reviewed_openrouter_providers)
    assert payload["provider"]["data_collection"] == "deny"
    assert payload["provider"]["only"] == reviewed_providers
    assert payload["provider"]["order"] == reviewed_providers
    assert payload["provider"]["zdr"] is True
    assert payload["stream"] is False
    assert payload["session_id"] == "thread-1"


def test_openrouter_chat_posts_to_chat_completions_and_audits_metadata(tmp_path, monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "gen-test",
                "model": "test/model",
                "choices": [{"message": {"content": "mock answer"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    monkeypatch.setattr(openrouter, "AUDIT_LOG", tmp_path / "audit_log.jsonl")
    async def run_call():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await openrouter.openrouter_chat(
                system="system text",
                user="user text",
                model_override="test/model",
                client=client,
                broker=_client_broker(tmp_path),
            )

    answer = asyncio.run(run_call())

    assert answer == "mock answer"
    assert requests[0].url.path.endswith("/chat/completions")
    body = json.loads(requests[0].content)
    reviewed_providers = list(openrouter.get_settings().reviewed_openrouter_providers)
    assert body["provider"]["data_collection"] == "deny"
    assert body["provider"]["only"] == reviewed_providers
    assert body["provider"]["order"] == reviewed_providers
    assert body["provider"]["zdr"] is True

    audit_text = (tmp_path / "audit_log.jsonl").read_text(encoding="utf-8")
    audit = json.loads(audit_text)
    assert "mock answer" not in audit_text
    assert "user text" not in audit_text
    assert audit["outcome"] == "completed"
    assert audit["prompt_tokens"] == 10
    assert audit["completion_tokens"] == 2
    assert audit["total_tokens"] == 12


def test_openrouter_chat_uses_fallback_on_primary_http_error(monkeypatch, tmp_path):
    models = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        models.append(body["model"])
        if len(models) == 1:
            return httpx.Response(500, json={"error": "primary failed"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "fallback answer"}}]})

    monkeypatch.setattr(openrouter, "AUDIT_LOG", tmp_path / "audit_log.jsonl")
    async def run_call():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await openrouter.openrouter_chat(
                system="system",
                user="user",
                model_override="primary/test",
                client=client,
                broker=_client_broker(tmp_path),
            )

    answer = asyncio.run(run_call())

    assert answer == "fallback answer"
    assert models == ["primary/test", openrouter.get_settings().fallback_model]


def test_openrouter_chat_audits_terminal_failure(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "provider unavailable"})

    monkeypatch.setattr(openrouter, "AUDIT_LOG", tmp_path / "audit_log.jsonl")

    async def run_call():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await openrouter.openrouter_chat(
                system="system",
                user="user",
                model_override="primary/test",
                client=client,
                broker=_client_broker(tmp_path),
            )

    with pytest.raises(openrouter.OpenRouterError):
        asyncio.run(run_call())

    audit = json.loads((tmp_path / "audit_log.jsonl").read_text(encoding="utf-8"))
    assert audit["outcome"] == "failed"
    assert audit["thread_id"] == "background"


def test_injected_client_blocks_secrets_before_http(tmp_path):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "no"}}]})

    async def run_call():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await openrouter.openrouter_chat(
                system="system",
                user="Use api_key=super-secret-value",
                model_override="test/model",
                client=client,
                broker=_client_broker(tmp_path),
            )

    with pytest.raises(DisclosureBlocked, match="sensitive content"):
        asyncio.run(run_call())
    assert requests == []


def test_openrouter_chat_delegates_to_shared_runtime_without_injected_client(monkeypatch):
    captured = {}

    class FakeEngine:
        async def ainvoke(self, **kwargs):
            captured.update(kwargs)
            from langchain_core.messages import AIMessage

            return AIMessage(content="routed answer")

    class FakeRuntime:
        engine = FakeEngine()

    monkeypatch.setattr(openrouter, "get_routing_runtime", lambda: FakeRuntime())

    answer = asyncio.run(
        openrouter.openrouter_chat(
            system="system",
            user="user",
            model_override="primary/test",
            session_id="thread-1",
        )
    )

    assert captured["disclosure_purpose"] == "chat"
    assert answer == "routed answer"
    assert captured["primary_model"] == "primary/test"
    assert captured["thread_id"] == "thread-1"


def test_openrouter_http_error_message_includes_provider_reason():
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": "test/model is not a valid model ID", "code": 400}},
    )
    exc = httpx.HTTPStatusError("bad request", request=request, response=response)

    assert openrouter._http_error_message(exc) == "test/model is not a valid model ID (code: 400)"


def test_langchain_agent_uses_shared_routed_model(monkeypatch):
    sentinel = object()
    captured = {}

    def fake_routed(model=None, reasoning_mode=None):
        captured["model"] = model
        return sentinel

    monkeypatch.setattr(react_agent, "get_routed_chat_model", fake_routed)

    assert react_agent.build_llm("primary/test") is sentinel
    assert captured["model"] == "primary/test"


def test_legacy_fallback_builder_is_alias_for_routed_model(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(react_agent, "get_routed_chat_model", lambda model=None, reasoning_mode=None: sentinel)

    assert react_agent.build_llm_with_fallback("primary/test") is sentinel


def test_vellum_prompt_includes_active_model_for_self_reporting():
    from agent.llm import providers as providers_mod

    providers_mod.get_provider_registry.cache_clear()
    registry = providers_mod.get_provider_registry()
    registry.set_active("deepseek/deepseek-v4-pro")

    messages = react_agent.vellum_prompt({"messages": []}, {"configurable": {"thread_id": "prompt-model-test"}})

    assert "Runtime selected model: deepseek/deepseek-v4-pro" in messages[0].content
    providers_mod.get_provider_registry.cache_clear()


def test_react_agent_wiring_uses_system_prompt_and_tools(monkeypatch):
    captured = {}

    def fake_build_agent_runtime(**kwargs):
        captured.update(kwargs)
        return "compiled-agent"

    monkeypatch.setattr(react_agent, "build_llm", lambda model=None, reasoning_mode=None: "llm")
    monkeypatch.setattr(react_agent, "build_checkpointer", lambda: "checkpointer")
    monkeypatch.setattr(react_agent, "_build_agent_runtime", fake_build_agent_runtime)

    compiled = react_agent.build_agent()

    assert compiled == "compiled-agent"
    assert captured["llm"] == "llm"
    assert captured["checkpointer"] == "checkpointer"
    assert {tool.name for tool in captured["tools"]} >= {
        "search_my_notes",
        "web_search",
        "search_amazon",
        "knowledge_wiki",
    }
    # plugin_mcp is the deferrable surface of the tool-search bridge
    assert "plugin_mcp" in captured["deferred_names"]
    assert "Always search the vault first" in react_agent.VELLUM_SYSTEM_PROMPT


def test_react_agent_uses_exact_selected_model_without_cross_model_fallback(monkeypatch):
    captured = {}

    def fake_build_agent_runtime(**kwargs):
        captured.update(kwargs)
        return "compiled-agent"

    def fail_if_cross_model_fallback_is_used(model=None):
        raise AssertionError("agent chat should not silently fall back to a different model")

    monkeypatch.setattr(react_agent, "build_llm", lambda model=None, reasoning_mode=None: f"llm:{model}")
    monkeypatch.setattr(react_agent, "build_llm_with_fallback", fail_if_cross_model_fallback_is_used)
    monkeypatch.setattr(react_agent, "build_checkpointer", lambda: "checkpointer")
    monkeypatch.setattr(react_agent, "_build_agent_runtime", fake_build_agent_runtime)

    compiled = react_agent.build_agent("deepseek/deepseek-v4-pro")

    assert compiled == "compiled-agent"
    assert captured["llm"] == "llm:deepseek/deepseek-v4-pro"


def test_async_react_agent_wiring_uses_async_checkpointer(monkeypatch):
    captured = {}

    def fake_build_agent_runtime(**kwargs):
        captured.update(kwargs)
        return "async-compiled-agent"

    async def fake_build_async_checkpointer():
        return "async-checkpointer"

    monkeypatch.setattr(react_agent, "build_llm", lambda model=None, reasoning_mode=None: "llm")
    monkeypatch.setattr(react_agent, "build_async_checkpointer", fake_build_async_checkpointer)
    monkeypatch.setattr(react_agent, "_build_agent_runtime", fake_build_agent_runtime)

    compiled = asyncio.run(react_agent.build_async_agent())

    assert compiled == "async-compiled-agent"
    assert captured["llm"] == "llm"
    assert captured["checkpointer"] == "async-checkpointer"
