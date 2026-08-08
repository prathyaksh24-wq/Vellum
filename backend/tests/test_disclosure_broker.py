from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

from agent.privacy.disclosure import (
    DestinationPolicy,
    DisclosureBlocked,
    DisclosureBroker,
    DisclosureGrant,
    DisclosureGrantStore,
    DisclosureModelAdapter,
    DisclosurePolicy,
    ProtectionMode,
)


def _broker(
    tmp_path,
    *,
    mode: ProtectionMode = ProtectionMode.protect_for_me,
    grant_store: DisclosureGrantStore | None = None,
) -> DisclosureBroker:
    return DisclosureBroker(
        policy=DisclosurePolicy(
            mode=mode,
            receipt_path=tmp_path / "privacy-receipts.jsonl",
            destinations={
                "openrouter": DestinationPolicy(
                    name="openrouter",
                    endpoint="https://openrouter.ai/api/v1",
                    approved_models=frozenset({"google/test"}),
                    data_collection="deny",
                    zdr=True,
                    prompt_logging=False,
                    response_caching=False,
                )
            },
        ),
        alias_key=b"test-alias-key",
        grant_store=grant_store,
    )


def test_protected_disclosure_pseudonymizes_and_restores_at_the_same_seam(tmp_path) -> None:
    broker = _broker(tmp_path)
    original = "Ask Jane Doe to email jane@example.com about the launch."

    prepared = broker.prepare_messages(
        [HumanMessage(content=original)],
        destination="openrouter",
        model="google/test",
        purpose="chat",
        thread_id="thread-1",
    )

    outbound = prepared.messages[0].content
    assert "Jane Doe" not in outbound
    assert "jane@example.com" not in outbound
    assert outbound.startswith("<PROTECTED>\n")
    assert "</PROTECTED>\n\n<QUERY>\n" in outbound
    assert outbound.endswith("\n</QUERY>")
    assert "[PERSON_" not in outbound
    assert "@masked.invalid" in outbound

    restored = prepared.restore_message(AIMessage(content=f"I will refer to {outbound}"))
    assert "Jane Doe" in restored.content
    assert "jane@example.com" in restored.content

    broker.complete(prepared, outcome="success")
    receipt_text = (tmp_path / "privacy-receipts.jsonl").read_text(encoding="utf-8")
    receipts = [json.loads(line) for line in receipt_text.splitlines()]
    assert [item["outcome"] for item in receipts] == ["authorized", "success"]
    assert receipts[-1]["categories"] == ["EMAIL", "PERSON"]
    assert receipts[-1]["transformations"] == [
        "meaning_preserving_scoped_alias",
        "privacy_boundary_tags",
    ]
    assert original not in receipt_text
    assert "Jane Doe" not in receipt_text
    assert "jane@example.com" not in receipt_text


def test_green_disclosure_is_tagged_as_query(tmp_path) -> None:
    prepared = _broker(tmp_path).prepare_messages(
        [HumanMessage(content="Explain photosynthesis")],
        destination="openrouter",
        model="google/test",
        purpose="chat",
        thread_id="thread-1",
    )

    assert prepared.messages[0].content == "<QUERY>\nExplain photosynthesis\n</QUERY>"
    assert "privacy_boundary_tags" in prepared.transformations


def test_each_outbound_message_is_classified_and_tagged_independently(tmp_path) -> None:
    prepared = _broker(tmp_path).prepare_messages(
        [
            SystemMessage(content="Answer briefly."),
            HumanMessage(content="Ask Jane Doe about the launch."),
        ],
        destination="openrouter",
        model="google/test",
        purpose="chat",
        thread_id="thread-1",
    )

    assert prepared.messages[0].content == "<QUERY>\nAnswer briefly.\n</QUERY>"
    assert prepared.messages[1].content.startswith(
        "<PROTECTED>\nProtected locally: PERSON\n</PROTECTED>\n\n<QUERY>\n"
    )
    assert "Jane Doe" not in prepared.messages[1].content


def test_full_context_keeps_context_but_still_aliases_identifiers(tmp_path) -> None:
    broker = _broker(tmp_path, mode=ProtectionMode.full_context)
    grant = DisclosureGrant(
        mode=ProtectionMode.full_context,
        destinations=frozenset({"openrouter"}),
        purposes=frozenset({"chat"}),
        thread_id="thread-1",
        categories=frozenset({"PERSON", "EMAIL"}),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    prepared = broker.prepare_messages(
        [HumanMessage(content="Email Jane Doe at jane@example.com")],
        destination="openrouter",
        model="google/test",
        purpose="chat",
        thread_id="thread-1",
        grant=grant,
    )

    outbound = prepared.messages[0].content
    assert outbound.startswith("<PROTECTED>\nProtected locally: EMAIL, PERSON")
    assert "<QUERY>" in outbound
    assert "Jane Doe" not in outbound
    assert "jane@example.com" not in outbound


def test_broker_uses_locally_issued_scoped_grant(tmp_path) -> None:
    store = DisclosureGrantStore(tmp_path / "grants.db")
    broker = _broker(
        tmp_path,
        mode=ProtectionMode.ask_before_sharing,
        grant_store=store,
    )
    grant = store.issue(
        mode=ProtectionMode.ask_before_sharing,
        destinations={"openrouter"},
        purposes={"chat"},
        thread_id="thread-1",
        categories={"PERSON"},
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    prepared = broker.prepare_messages(
        [HumanMessage(content="Ask Jane Doe")],
        destination="openrouter",
        model="google/test",
        purpose="chat",
        thread_id="thread-1",
    )

    assert prepared.decision_source == f"grant:{grant.id}"
    assert "Jane Doe" not in prepared.messages[0].content


@pytest.mark.parametrize(
    "mode",
    [
        ProtectionMode.ask_before_sharing,
        ProtectionMode.protect_for_me,
        ProtectionMode.full_context,
    ],
)
def test_hard_secrets_are_blocked_in_every_cloud_mode(tmp_path, mode: ProtectionMode) -> None:
    broker = _broker(tmp_path, mode=mode)

    with pytest.raises(DisclosureBlocked, match="sensitive content"):
        broker.prepare_messages(
            [HumanMessage(content="Use api_key=super-secret-value")],
            destination="openrouter",
            model="google/test",
            purpose="chat",
            thread_id="thread-1",
        )

    receipt_text = (tmp_path / "privacy-receipts.jsonl").read_text(encoding="utf-8")
    assert "super-secret-value" not in receipt_text
    assert json.loads(receipt_text)["outcome"] == "blocked"


def test_full_context_requires_a_scoped_unexpired_grant(tmp_path) -> None:
    broker = _broker(tmp_path, mode=ProtectionMode.full_context)
    messages = [HumanMessage(content="Email Jane Doe at jane@example.com")]

    with pytest.raises(DisclosureBlocked, match="approval"):
        broker.prepare_messages(
            messages,
            destination="openrouter",
            model="google/test",
            purpose="chat",
            thread_id="thread-1",
        )

    grant = DisclosureGrant(
        mode=ProtectionMode.full_context,
        destinations=frozenset({"openrouter"}),
        purposes=frozenset({"chat"}),
        thread_id="thread-1",
        categories=frozenset({"PERSON", "EMAIL"}),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    prepared = broker.prepare_messages(
        messages,
        destination="openrouter",
        model="google/test",
        purpose="chat",
        thread_id="thread-1",
        grant=grant,
    )

    assert "<PROTECTED>" in prepared.messages[0].content
    assert "<QUERY>" in prepared.messages[0].content
    assert "Jane Doe" not in prepared.messages[0].content
    assert "jane@example.com" not in prepared.messages[0].content
    assert prepared.decision_source == f"grant:{grant.id}"
    assert prepared.transformations == (
        "meaning_preserving_scoped_alias",
        "privacy_boundary_tags",
    )


def test_expired_grant_cannot_expand_the_scope(tmp_path) -> None:
    broker = _broker(tmp_path, mode=ProtectionMode.full_context)
    grant = DisclosureGrant(
        mode=ProtectionMode.full_context,
        destinations=frozenset({"openrouter"}),
        purposes=frozenset({"chat"}),
        thread_id="thread-1",
        categories=frozenset({"PERSON"}),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    with pytest.raises(DisclosureBlocked, match="approval"):
        broker.prepare_messages(
            [HumanMessage(content="Ask Jane Doe")],
            destination="openrouter",
            model="google/test",
            purpose="chat",
            thread_id="thread-1",
            grant=grant,
        )


def test_destination_and_model_allowlists_fail_closed(tmp_path) -> None:
    broker = _broker(tmp_path)

    with pytest.raises(DisclosureBlocked, match="destination"):
        broker.prepare_messages(
            [HumanMessage(content="hello")],
            destination="openai",
            model="openai/gpt-test",
            purpose="chat",
            thread_id="thread-1",
        )

    with pytest.raises(DisclosureBlocked, match="model"):
        broker.prepare_messages(
            [HumanMessage(content="hello")],
            destination="openrouter",
            model="unreviewed/model",
            purpose="chat",
            thread_id="thread-1",
        )


def test_ask_before_sharing_requires_approval_even_for_green_content(tmp_path) -> None:
    broker = _broker(tmp_path, mode=ProtectionMode.ask_before_sharing)

    with pytest.raises(DisclosureBlocked, match="approval"):
        broker.prepare_messages(
            [HumanMessage(content="Explain photosynthesis")],
            destination="openrouter",
            model="google/test",
            purpose="chat",
            thread_id="thread-1",
        )

    grant = DisclosureGrant(
        mode=ProtectionMode.ask_before_sharing,
        destinations=frozenset({"openrouter"}),
        purposes=frozenset({"chat"}),
        thread_id="thread-1",
        categories=frozenset(),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    prepared = broker.prepare_messages(
        [HumanMessage(content="Explain photosynthesis")],
        destination="openrouter",
        model="google/test",
        purpose="chat",
        thread_id="thread-1",
        grant=grant,
    )

    assert prepared.messages[0].content == (
        "<QUERY>\nExplain photosynthesis\n</QUERY>"
    )


class FakeExternalModel:
    def __init__(self) -> None:
        self.calls = 0
        self.seen_messages = []

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        self.seen_messages = messages
        return AIMessage(content=f"Cloud saw: {messages[0].content}")

    async def astream(self, messages, **kwargs):
        self.calls += 1
        self.seen_messages = messages
        alias = messages[0].content
        split_at = len(alias) // 2
        yield AIMessageChunk(content=f"Answer about {alias[:split_at]}")
        yield AIMessageChunk(content=alias[split_at:])

    def bind_tools(self, tools):
        return self


class FakeExternalAdapter:
    provider = "openrouter"

    def __init__(self, model: FakeExternalModel) -> None:
        self.model = model

    def build_model(self, **kwargs):
        return self.model


def _protected_model(tmp_path):
    external = FakeExternalModel()
    adapter = DisclosureModelAdapter(
        adapter=FakeExternalAdapter(external),
        broker=_broker(tmp_path),
    )
    model = adapter.build_model(
        target=SimpleNamespace(model="google/test"),
        thread_id="thread-1",
    )
    return model, external


@pytest.mark.asyncio
async def test_model_adapter_protects_before_io_and_restores_after_io(tmp_path) -> None:
    model, external = _protected_model(tmp_path)

    result = await model.ainvoke(
        [HumanMessage(content="Ask Jane Doe to email jane@example.com")]
    )

    outbound = external.seen_messages[0].content
    assert external.calls == 1
    assert "Jane Doe" not in outbound
    assert "jane@example.com" not in outbound
    assert "Jane Doe" in result.content
    assert "jane@example.com" in result.content


@pytest.mark.asyncio
async def test_model_adapter_blocks_secrets_before_external_model_call(tmp_path) -> None:
    model, external = _protected_model(tmp_path)

    with pytest.raises(DisclosureBlocked, match="sensitive content"):
        await model.ainvoke(
            [HumanMessage(content="Use api_key=super-secret-value")]
        )

    assert external.calls == 0


@pytest.mark.asyncio
async def test_model_adapter_restores_aliases_split_across_stream_chunks(tmp_path) -> None:
    model, external = _protected_model(tmp_path)

    chunks = [
        chunk
        async for chunk in model.astream([HumanMessage(content="Jane Doe")])
    ]

    assert external.calls == 1
    assert "Jane Doe" not in external.seen_messages[0].content
    assert "".join(chunk.content for chunk in chunks) == "Answer about Jane Doe"


def test_aliases_are_stable_only_inside_the_same_scope(tmp_path) -> None:
    broker = _broker(tmp_path)
    messages = [HumanMessage(content="Jane Doe")]

    first = broker.prepare_messages(
        messages,
        destination="openrouter",
        model="google/test",
        purpose="chat",
        thread_id="thread-1",
    )
    repeated = broker.prepare_messages(
        messages,
        destination="openrouter",
        model="google/test",
        purpose="chat",
        thread_id="thread-1",
    )
    other_thread = broker.prepare_messages(
        messages,
        destination="openrouter",
        model="google/test",
        purpose="chat",
        thread_id="thread-2",
    )
    other_purpose = broker.prepare_messages(
        messages,
        destination="openrouter",
        model="google/test",
        purpose="digest",
        thread_id="thread-1",
    )

    assert first.messages[0].content == repeated.messages[0].content
    assert first.messages[0].content != other_thread.messages[0].content
    assert first.messages[0].content != other_purpose.messages[0].content


@pytest.mark.asyncio
async def test_model_failure_records_metadata_without_prompt_content(tmp_path) -> None:
    class FailingExternalModel(FakeExternalModel):
        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            self.seen_messages = messages
            raise RuntimeError("provider failed")

    external = FailingExternalModel()
    adapter = DisclosureModelAdapter(
        adapter=FakeExternalAdapter(external),
        broker=_broker(tmp_path),
    )
    model = adapter.build_model(
        target=SimpleNamespace(model="google/test"),
        thread_id="thread-1",
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        await model.ainvoke([HumanMessage(content="Ask Jane Doe")])

    receipt_text = (tmp_path / "privacy-receipts.jsonl").read_text(
        encoding="utf-8"
    )
    receipts = [json.loads(line) for line in receipt_text.splitlines()]
    assert [item["outcome"] for item in receipts] == ["authorized", "failed"]
    assert external.calls == 1
    assert "Jane Doe" not in external.seen_messages[0].content
    assert "Jane Doe" not in receipt_text
