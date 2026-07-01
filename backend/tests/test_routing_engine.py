from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, HumanMessage

from agent.llm.routing.engine import RoutingEngine
from agent.llm.routing.models import CredentialRecord, FallbackTarget, RoutingTerminalError
from agent.llm.routing.pool import CredentialPool
from agent.llm.routing.store import RoutingStore


class FakeStatusError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = type("Response", (), {"status_code": status_code, "headers": {}})()


class StaticResolver:
    def resolve(self, credential: CredentialRecord) -> str:
        return credential.label


class FakeModel:
    def __init__(self, adapter: "FakeAdapter", outcome) -> None:
        self.adapter = adapter
        self.outcome = outcome

    def bind_tools(self, tools):
        self.adapter.bound_tools = list(tools)
        return self

    async def ainvoke(self, messages, **kwargs):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class FakeAdapter:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, str]] = []
        self.bound_tools: list[object] = []

    def build_model(self, *, target, secret, **kwargs):
        self.calls.append((target.model, secret))
        return FakeModel(self, self.outcomes.pop(0))


def add_credential(store: RoutingStore, provider: str, label: str) -> None:
    store.upsert_credential(
        CredentialRecord(
            provider=provider,
            label=label,
            source=f"keyring:{label}",
            fingerprint=f"fp:{label}",
        )
    )


def build_engine(tmp_path, *, openrouter_outcomes, openai_outcomes=()):
    store = RoutingStore(tmp_path / "routing.db")
    pool = CredentialPool(store)
    openrouter = FakeAdapter(list(openrouter_outcomes))
    openai = FakeAdapter(list(openai_outcomes))
    engine = RoutingEngine(
        store=store,
        pool=pool,
        secret_resolver=StaticResolver(),
        adapters={"openrouter": openrouter, "openai": openai},
        async_sleep=lambda _seconds: asyncio.sleep(0),
        jitter=lambda: 0.0,
    )
    return store, engine, openrouter, openai


def test_pool_rotation_precedes_model_fallback(tmp_path) -> None:
    async def scenario() -> None:
        store, engine, adapter, _ = build_engine(
            tmp_path,
            openrouter_outcomes=[
                FakeStatusError(401, "expired"),
                AIMessage(content="primary on second key"),
            ],
        )
        add_credential(store, "openrouter", "key-1")
        add_credential(store, "openrouter", "key-2")
        store.replace_fallbacks(
            [FallbackTarget(provider="openai", model="openai/fallback")]
        )

        result = await engine.ainvoke(
            messages=[HumanMessage(content="hello")],
            primary_model="google/primary",
        )

        assert result.content == "primary on second key"
        assert adapter.calls == [
            ("google/primary", "key-1"),
            ("google/primary", "key-2"),
        ]

    asyncio.run(scenario())


def test_model_unavailable_uses_fallback_and_next_call_restores_primary(tmp_path) -> None:
    async def scenario() -> None:
        store, engine, openrouter, openai = build_engine(
            tmp_path,
            openrouter_outcomes=[
                FakeStatusError(404, "missing"),
                AIMessage(content="primary restored"),
            ],
            openai_outcomes=[AIMessage(content="fallback")],
        )
        add_credential(store, "openrouter", "or-key")
        add_credential(store, "openai", "oa-key")
        store.replace_fallbacks(
            [FallbackTarget(provider="openai", model="openai/fallback")]
        )

        first = await engine.ainvoke(
            messages=[HumanMessage(content="one")],
            primary_model="google/primary",
        )
        second = await engine.ainvoke(
            messages=[HumanMessage(content="two")],
            primary_model="google/primary",
        )

        assert first.content == "fallback"
        assert second.content == "primary restored"
        assert openrouter.calls == [
            ("google/primary", "or-key"),
            ("google/primary", "or-key"),
        ]
        assert openai.calls == [("openai/fallback", "oa-key")]

    asyncio.run(scenario())


def test_generic_429_retries_same_key_once(tmp_path) -> None:
    async def scenario() -> None:
        store, engine, adapter, _ = build_engine(
            tmp_path,
            openrouter_outcomes=[
                FakeStatusError(429, "transient"),
                AIMessage(content="recovered"),
            ],
        )
        add_credential(store, "openrouter", "same-key")

        result = await engine.ainvoke(
            messages=[HumanMessage(content="hello")],
            primary_model="google/primary",
        )

        assert result.content == "recovered"
        assert adapter.calls == [
            ("google/primary", "same-key"),
            ("google/primary", "same-key"),
        ]

    asyncio.run(scenario())


def test_invalid_request_does_not_fallback_or_leak_raw_error(tmp_path) -> None:
    async def scenario() -> None:
        store, engine, _, openai = build_engine(
            tmp_path,
            openrouter_outcomes=[FakeStatusError(400, "Bearer sk-secret invalid parameter")],
            openai_outcomes=[AIMessage(content="must not run")],
        )
        add_credential(store, "openrouter", "or-key")
        add_credential(store, "openai", "oa-key")
        store.replace_fallbacks(
            [FallbackTarget(provider="openai", model="openai/fallback")]
        )

        try:
            await engine.ainvoke(
                messages=[HumanMessage(content="hello")],
                primary_model="google/primary",
            )
        except RoutingTerminalError as exc:
            assert "sk-secret" not in str(exc)
            assert exc.failures[0].summary == "provider rejected the request"
        else:
            raise AssertionError("invalid requests must fail without fallback")
        assert openai.calls == []

    asyncio.run(scenario())


def test_tools_are_bound_on_the_selected_attempt(tmp_path) -> None:
    async def scenario() -> None:
        store, engine, adapter, _ = build_engine(
            tmp_path,
            openrouter_outcomes=[AIMessage(content="", tool_calls=[{"name": "lookup", "args": {}, "id": "1"}])],
        )
        add_credential(store, "openrouter", "or-key")
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]

        result = await engine.ainvoke(
            messages=[HumanMessage(content="lookup")],
            primary_model="google/primary",
            tools=tools,
        )

        assert result.tool_calls[0]["name"] == "lookup"
        assert adapter.bound_tools == tools

    asyncio.run(scenario())
