import json
from types import SimpleNamespace

import pytest

from agent import api
from agent.app_actions.models import (
    AppActionContext,
    SurfacePresentation,
    WorkspaceLayoutSnapshot,
)
from agent.app_actions.runtime import AppActionRuntime
from agent.conversations.lifecycle import ConversationLifecycle
from agent.conversations.sharing import ConversationShareService
import agent.skills.curator_runtime as curator_runtime


async def passthrough(stream, _audit):
    async for chunk in stream:
        yield chunk


def parse_sse(payload: str) -> list[tuple[str, dict]]:
    events = []
    for block in payload.split("\n\n"):
        if not block.strip():
            continue
        event = next(line[6:].strip() for line in block.splitlines() if line.startswith("event:"))
        data = next(line[5:].strip() for line in block.splitlines() if line.startswith("data:"))
        events.append((event, json.loads(data)))
    return events


@pytest.mark.asyncio
async def test_submitted_sidebar_nlp_streams_receipt_without_calling_agent(monkeypatch) -> None:
    monkeypatch.setattr(curator_runtime, "get_curator_runtime", lambda: SimpleNamespace(mark_activity=lambda: None))
    monkeypatch.setattr(api, "_audited_turn_stream", passthrough)
    monkeypatch.setattr(api, "_app_action_runtime", AppActionRuntime())

    async def agent_must_not_run(**_kwargs):
        raise AssertionError("ordinary agent path must not run for a matched App Action")
        yield ""

    monkeypatch.setattr(api, "_stream_agent_turn", agent_must_not_run)
    response = await api.chat_stream(api.ChatRequest(
        message="hide the sidebar",
        thread_id="chat-1",
        action_context=AppActionContext(
            source="ui",
            workspace_layout=WorkspaceLayoutSnapshot(
                revision=0,
                surfaces={"sidebar": SurfacePresentation(visible=True)},
            ),
        ),
    ))
    body = "".join([chunk async for chunk in response.body_iterator])
    events = parse_sse(body)
    names = [name for name, _ in events]
    receipt = next(data["receipt"] for name, data in events if name == "app.action.receipt")
    completed = next(data["response"] for name, data in events if name == "response.completed")

    assert names == [
        "response.created",
        "app.action.requested",
        "app.action.receipt",
        "response.output_text.delta",
        "response.completed",
    ]
    assert receipt["source"] == "nlp"
    assert receipt["status"] == "applied"
    assert receipt["result"]["workspace_layout_patch"]["surfaces"]["sidebar"]["visible"] is False
    assert completed["output_text"] == "Sidebar hidden."


@pytest.mark.asyncio
async def test_raw_action_message_works_inside_a_specialist_chat(monkeypatch) -> None:
    monkeypatch.setattr(curator_runtime, "get_curator_runtime", lambda: SimpleNamespace(mark_activity=lambda: None))
    monkeypatch.setattr(api, "_audited_turn_stream", passthrough)
    monkeypatch.setattr(api, "_app_action_runtime", AppActionRuntime())

    async def agent_must_not_run(**_kwargs):
        raise AssertionError("specialist context must not hide a submitted interface action")
        yield ""

    monkeypatch.setattr(api, "_stream_agent_turn", agent_must_not_run)
    response = await api.chat_stream(api.ChatRequest(
        message=(
            "[Vellum UI context: the user is currently chatting in the Sports Agent view.]\n\n"
            "use light mode"
        ),
        action_message="use light mode",
        thread_id="sports-chat-1",
        action_context=AppActionContext(source="ui"),
    ))
    body = "".join([chunk async for chunk in response.body_iterator])
    events = parse_sse(body)
    receipt = next(data["receipt"] for name, data in events if name == "app.action.receipt")

    assert receipt["status"] == "applied"
    assert receipt["target"]["id"] == "workspace"
    assert receipt["result"]["presentation"]["properties"]["theme"] == "light"


def test_ordinary_conversation_is_not_classified_as_an_app_action() -> None:
    subject = AppActionRuntime()

    assert subject.match_submission("What are the benefits of a sidebar in a research app?") is None


@pytest.mark.asyncio
async def test_forked_chat_seeds_model_history_and_attachment_content_once(monkeypatch, tmp_path) -> None:
    lifecycle = ConversationLifecycle(
        path=tmp_path / "conversations.json",
        conversation_id_factory=lambda: "chat-fork",
    )
    lifecycle.save("chat-source", {
        "title": "Source",
        "messages": [
            {
                "id": "u1",
                "role": "user",
                "text": "What is in this image?",
                "attachments": [{
                    "name": "diagram.png",
                    "kind": "image",
                    "mime_type": "image/png",
                    "data_url": "data:image/png;base64,ZmFrZQ==",
                }],
            },
            {"id": "a1", "role": "assistant", "text": "It is a diagram."},
        ],
    })
    lifecycle.fork("chat-source", through_message_id="a1")
    monkeypatch.setattr(api, "_conversation_lifecycle", lambda: lifecycle)

    class SeedAgent:
        def __init__(self):
            self.messages = []
            self.updates = []

        async def aget_state(self, config, **_kwargs):
            assert config["configurable"]["thread_id"] == "chat-fork"
            return SimpleNamespace(values={"messages": list(self.messages)})

        async def aupdate_state(self, _config, values, **_kwargs):
            self.updates.append(values)
            self.messages.extend(values["messages"])

    seeded_agent = SeedAgent()
    monkeypatch.setattr(api, "agent", seeded_agent)

    first = await api._ensure_fork_runtime_context("chat-fork", model="test-model", reasoning_mode=None)
    second = await api._ensure_fork_runtime_context("chat-fork", model="test-model", reasoning_mode=None)

    assert first == 2
    assert second == 0
    assert len(seeded_agent.updates) == 1
    assert seeded_agent.messages[0]["role"] == "user"
    assert seeded_agent.messages[0]["content"] == [
        {"type": "text", "text": "What is in this image?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,ZmFrZQ=="}},
    ]
    assert seeded_agent.messages[1] == {"role": "assistant", "content": "It is a diagram."}


@pytest.mark.asyncio
async def test_conversation_nlp_actions_persist_and_bypass_the_agent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(curator_runtime, "get_curator_runtime", lambda: SimpleNamespace(mark_activity=lambda: None))
    monkeypatch.setattr(api, "_audited_turn_stream", passthrough)
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json")
    lifecycle.save("chat-current", {
        "thread_id": "thread-current",
        "title": "Current chat",
        "messages": [],
    })
    lifecycle.save("chat-old", {"title": "Release planning", "messages": []})
    monkeypatch.setattr(api, "_app_action_runtime", AppActionRuntime(conversation_lifecycle=lifecycle))

    async def agent_must_not_run(**_kwargs):
        raise AssertionError("ordinary agent path must not run for a matched conversation action")
        yield ""

    monkeypatch.setattr(api, "_stream_agent_turn", agent_must_not_run)

    pin_response = await api.chat_stream(api.ChatRequest(
        message="pin this chat",
        thread_id="thread-current",
    ))
    pin_events = parse_sse("".join([chunk async for chunk in pin_response.body_iterator]))
    archive_response = await api.chat_stream(api.ChatRequest(
        message='archive the chat called "Release planning"',
        thread_id="thread-current",
    ))
    archive_events = parse_sse("".join([chunk async for chunk in archive_response.body_iterator]))

    pin_receipt = next(data["receipt"] for name, data in pin_events if name == "app.action.receipt")
    archive_receipt = next(data["receipt"] for name, data in archive_events if name == "app.action.receipt")
    reloaded = ConversationLifecycle(path=lifecycle.path)

    assert pin_receipt["status"] == "applied"
    assert pin_receipt["source"] == "nlp"
    assert pin_receipt["target"]["id"] == "chat-current"
    assert archive_receipt["target"]["id"] == "chat-old"
    assert reloaded.get("chat-current")["pinned"] is True
    assert reloaded.get("chat-current")["archived"] is False
    assert reloaded.get("chat-old")["archived"] is True


@pytest.mark.asyncio
async def test_fork_and_share_nlp_actions_run_through_the_live_chat_stream(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(curator_runtime, "get_curator_runtime", lambda: SimpleNamespace(mark_activity=lambda: None))
    monkeypatch.setattr(api, "_audited_turn_stream", passthrough)
    lifecycle = ConversationLifecycle(
        path=tmp_path / "conversations.json",
        conversation_id_factory=lambda: "chat-fork",
    )
    lifecycle.save("chat-current", {
        "thread_id": "thread-current",
        "title": "Current chat",
        "messages": [
            {"id": "u1", "role": "user", "text": "Question"},
            {"id": "a1", "role": "assistant", "text": "Answer"},
            {"id": "u2", "role": "user", "text": "Later"},
        ],
    })
    monkeypatch.setattr(api, "_app_action_runtime", AppActionRuntime(
        conversation_lifecycle=lifecycle,
        conversation_sharing=ConversationShareService(export_dir=tmp_path / "exports"),
    ))

    async def agent_must_not_run(**_kwargs):
        raise AssertionError("pure conversation actions must not reach the model")
        yield ""

    monkeypatch.setattr(api, "_stream_agent_turn", agent_must_not_run)
    fork_response = await api.chat_stream(api.ChatRequest(
        message="fork this chat through message a1",
        thread_id="thread-current",
    ))
    share_response = await api.chat_stream(api.ChatRequest(
        message="share this chat",
        thread_id="thread-current",
    ))

    fork_events = parse_sse("".join([chunk async for chunk in fork_response.body_iterator]))
    share_events = parse_sse("".join([chunk async for chunk in share_response.body_iterator]))
    fork_receipt = next(data["receipt"] for name, data in fork_events if name == "app.action.receipt")
    share_receipt = next(data["receipt"] for name, data in share_events if name == "app.action.receipt")

    assert fork_receipt["status"] == "applied"
    assert [message["id"] for message in lifecycle.get("chat-fork")["messages"]] == ["u1", "a1"]
    assert share_receipt["status"] == "confirmation_required"
    assert share_receipt["result"]["share_review"]["destination"] == "local_export"
    assert not (tmp_path / "exports").exists()


@pytest.mark.asyncio
async def test_pure_conversation_keeps_the_existing_agent_stream(monkeypatch) -> None:
    monkeypatch.setattr(curator_runtime, "get_curator_runtime", lambda: SimpleNamespace(mark_activity=lambda: None))
    monkeypatch.setattr(api, "_audited_turn_stream", passthrough)
    monkeypatch.setattr(api, "_app_action_runtime", AppActionRuntime())
    streamed_messages = []

    async def agent_stream(**kwargs):
        streamed_messages.append(kwargs["clean_message"])
        yield 'event: response.created\ndata: {"thread_id":"chat-ordinary"}\n\n'
        yield 'event: response.completed\ndata: {"response":{"thread_id":"chat-ordinary","output_text":"Ordinary answer.","tools":[],"sources":[]}}\n\n'

    monkeypatch.setattr(api, "_stream_agent_turn", agent_stream)
    response = await api.chat_stream(api.ChatRequest(
        message="Explain why sidebars help research",
        thread_id="chat-ordinary",
    ))
    events = parse_sse("".join([chunk async for chunk in response.body_iterator]))

    assert streamed_messages == ["Explain why sidebars help research"]
    assert all(not name.startswith("app.action.") for name, _data in events)
    assert next(
        data["response"]["output_text"]
        for name, data in events
        if name == "response.completed"
    ) == "Ordinary answer."


@pytest.mark.asyncio
async def test_mixed_safe_action_continues_the_ordinary_agent_stream(monkeypatch) -> None:
    monkeypatch.setattr(curator_runtime, "get_curator_runtime", lambda: SimpleNamespace(mark_activity=lambda: None))
    monkeypatch.setattr(api, "_audited_turn_stream", passthrough)
    monkeypatch.setattr(api, "_app_action_runtime", AppActionRuntime())
    streamed_messages = []

    async def agent_stream(**kwargs):
        streamed_messages.append(kwargs["clean_message"])
        yield 'event: response.created\ndata: {"thread_id":"chat-mixed"}\n\n'
        yield 'event: response.output_text.delta\ndata: {"delta":"Bitcoin answer."}\n\n'
        yield 'event: response.completed\ndata: {"response":{"thread_id":"chat-mixed","output_text":"Bitcoin answer.","tools":[],"sources":[]}}\n\n'

    monkeypatch.setattr(api, "_stream_agent_turn", agent_stream)
    response = await api.chat_stream(api.ChatRequest(
        message="hide the sidebar, open settings, and tell me about Bitcoin",
        thread_id="chat-mixed",
        action_context=AppActionContext(
            source="ui",
            workspace_layout=WorkspaceLayoutSnapshot(
                revision=0,
                surfaces={
                    "sidebar": SurfacePresentation(visible=True),
                    "settings": SurfacePresentation(visible=False),
                },
            ),
        ),
    ))
    events = parse_sse("".join([chunk async for chunk in response.body_iterator]))

    requested = [data for name, data in events if name == "app.action.requested"]
    receipts = [data["receipt"] for name, data in events if name == "app.action.receipt"]
    completed = next(data["response"] for name, data in events if name == "response.completed")

    assert [event["turn_kind"] for event in requested] == ["mixed", "mixed"]
    assert [receipt["status"] for receipt in receipts] == ["applied", "applied"]
    assert [receipt["result"]["workspace_layout_patch"]["base_revision"] for receipt in receipts] == [0, 1]
    assert [name for name, _data in events[:5]] == [
        "response.created",
        "app.action.requested",
        "app.action.receipt",
        "app.action.requested",
        "app.action.receipt",
    ]
    assert streamed_messages == ["tell me about Bitcoin"]
    assert completed["output_text"] == "Bitcoin answer."


@pytest.mark.asyncio
async def test_mixed_delete_waits_for_confirmation_without_blocking_answer(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(curator_runtime, "get_curator_runtime", lambda: SimpleNamespace(mark_activity=lambda: None))
    monkeypatch.setattr(api, "_audited_turn_stream", passthrough)
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json")
    lifecycle.save("chat-current", {
        "thread_id": "thread-current",
        "title": "Current chat",
        "messages": [],
    })
    monkeypatch.setattr(api, "_app_action_runtime", AppActionRuntime(conversation_lifecycle=lifecycle))
    streamed_messages = []

    async def agent_stream(**kwargs):
        streamed_messages.append(kwargs["clean_message"])
        yield 'event: response.created\ndata: {"thread_id":"thread-current"}\n\n'
        yield 'event: response.completed\ndata: {"response":{"thread_id":"thread-current","output_text":"Summary.","tools":[],"sources":[]}}\n\n'

    monkeypatch.setattr(api, "_stream_agent_turn", agent_stream)
    response = await api.chat_stream(api.ChatRequest(
        message="delete this chat and summarize Bitcoin",
        thread_id="thread-current",
    ))
    events = parse_sse("".join([chunk async for chunk in response.body_iterator]))
    receipt = next(data["receipt"] for name, data in events if name == "app.action.receipt")

    assert receipt["status"] == "confirmation_required"
    assert receipt["confirmation"]["token"]
    assert streamed_messages == ["summarize Bitcoin"]
    assert lifecycle.get("chat-current") is not None


@pytest.mark.asyncio
async def test_unavailable_action_returns_receipt_and_never_falls_back_to_agent(monkeypatch) -> None:
    monkeypatch.setattr(curator_runtime, "get_curator_runtime", lambda: SimpleNamespace(mark_activity=lambda: None))
    monkeypatch.setattr(api, "_audited_turn_stream", passthrough)
    monkeypatch.setattr(
        api,
        "_app_action_runtime",
        AppActionRuntime(action_availability=lambda _definition, _context: False),
    )

    async def agent_must_not_run(**_kwargs):
        raise AssertionError("unavailable App Actions must not become simulated conversation work")
        yield ""

    monkeypatch.setattr(api, "_stream_agent_turn", agent_must_not_run)
    response = await api.chat_stream(api.ChatRequest(
        message="hide the sidebar",
        thread_id="old-chat",
    ))
    events = parse_sse("".join([chunk async for chunk in response.body_iterator]))
    receipt = next(data["receipt"] for name, data in events if name == "app.action.receipt")

    assert receipt["status"] == "unavailable"
    assert receipt["error_code"] == "ACTION_UNAVAILABLE"
    assert receipt["message"] == "Set sidebar visibility is currently unavailable."
