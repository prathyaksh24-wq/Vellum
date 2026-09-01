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


def test_ordinary_conversation_is_not_classified_as_an_app_action() -> None:
    subject = AppActionRuntime()

    assert subject.match_submission("What are the benefits of a sidebar in a research app?") is None
