import json
import asyncio

import httpx

from agent.graph import agent as react_agent
from agent.llm import openrouter


def test_openrouter_payload_enforces_privacy_policy():
    payload = openrouter._build_payload(
        system="system",
        user="user",
        model="test/model",
        max_tokens=128,
        temperature=0.2,
        session_id="thread-1",
    )

    assert payload["provider"]["data_collection"] == "deny"
    assert payload["provider"]["order"] == ["Fireworks", "Together", "DeepInfra"]
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
            )

    answer = asyncio.run(run_call())

    assert answer == "mock answer"
    assert requests[0].url.path.endswith("/chat/completions")
    body = json.loads(requests[0].content)
    assert body["provider"]["data_collection"] == "deny"
    assert body["provider"]["order"] == ["Fireworks", "Together", "DeepInfra"]
    assert body["provider"]["zdr"] is True

    audit = (tmp_path / "audit_log.jsonl").read_text(encoding="utf-8")
    assert "mock answer" not in audit
    assert "user text" not in audit
    assert "gen-test" in audit


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
            )

    answer = asyncio.run(run_call())

    assert answer == "fallback answer"
    assert models == ["primary/test", openrouter.get_settings().fallback_model]


def test_openrouter_http_error_message_includes_provider_reason():
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": "test/model is not a valid model ID", "code": 400}},
    )
    exc = httpx.HTTPStatusError("bad request", request=request, response=response)

    assert openrouter._http_error_message(exc) == "test/model is not a valid model ID (code: 400)"


def test_langchain_openrouter_provider_policy_uses_extra_body():
    llm = react_agent.build_llm()

    assert llm.extra_body["provider"]["data_collection"] == "deny"
    assert llm.extra_body["provider"]["order"] == ["Fireworks", "Together", "DeepInfra"]
    assert llm.extra_body["provider"]["zdr"] is True
    assert "provider" not in llm.model_kwargs


def test_react_agent_wiring_uses_system_prompt_and_tools(monkeypatch):
    captured = {}

    def fake_create_react_agent(**kwargs):
        captured.update(kwargs)
        return "compiled-agent"

    monkeypatch.setattr(react_agent, "build_llm", lambda model=None: "llm")
    monkeypatch.setattr(react_agent, "build_checkpointer", lambda: "checkpointer")
    monkeypatch.setattr(react_agent, "create_react_agent", fake_create_react_agent)

    compiled = react_agent.build_agent()

    assert compiled == "compiled-agent"
    assert captured["model"] == "llm"
    assert captured["checkpointer"] == "checkpointer"
    assert captured["prompt"] == react_agent.VELLUM_SYSTEM_PROMPT
    assert {tool.name for tool in captured["tools"]} >= {"search_my_notes", "web_search", "search_amazon"}
    assert "Always search the vault first" in react_agent.VELLUM_SYSTEM_PROMPT


def test_async_react_agent_wiring_uses_async_checkpointer(monkeypatch):
    captured = {}

    def fake_create_react_agent(**kwargs):
        captured.update(kwargs)
        return "async-compiled-agent"

    async def fake_build_async_checkpointer():
        return "async-checkpointer"

    monkeypatch.setattr(react_agent, "build_llm", lambda model=None: "llm")
    monkeypatch.setattr(react_agent, "build_async_checkpointer", fake_build_async_checkpointer)
    monkeypatch.setattr(react_agent, "create_react_agent", fake_create_react_agent)

    compiled = asyncio.run(react_agent.build_async_agent())

    assert compiled == "async-compiled-agent"
    assert captured["model"] == "llm"
    assert captured["checkpointer"] == "async-checkpointer"
