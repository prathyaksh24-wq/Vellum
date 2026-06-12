import asyncio
import json

from agent import api
from agent.agents.live_dispatcher import LiveAgentResult


def test_run_agent_uses_live_dispatcher_before_main_agent(monkeypatch):
    async def _should_not_call(*args, **kwargs):
        raise AssertionError("main graph agent should not run for handled sports turns")

    class FakeDispatcher:
        def maybe_handle(self, message, thread_id):
            return LiveAgentResult(
                handled=True,
                agent_name="SportsAgent",
                answer="Sports Pupil answer",
                tools=["sports_agent", "web_search"],
                sources=[
                    {
                        "url": "https://www.nba.com/news/finals",
                        "title": "NBA Finals",
                        "snippet": "Finals preview",
                        "domain": "nba.com",
                    }
                ],
            )

    monkeypatch.setattr(api, "_live_dispatcher", FakeDispatcher())
    monkeypatch.setattr(api.agent, "ainvoke", _should_not_call)
    monkeypatch.setattr(api.asyncio, "create_task", lambda coro: coro.close())

    response = asyncio.run(api._run_agent("NBA Finals update", "thread-1", None))

    assert response.answer == "Sports Pupil answer"
    assert response.thread_id == "thread-1"
    assert response.tools == ["sports_agent", "web_search"]
    assert response.sources[0].url == "https://www.nba.com/news/finals"


def _parse_sse(chunks):
    events = []
    for chunk in chunks:
        event = "message"
        data = ""
        for line in chunk.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data += line[len("data:"):].strip()
        events.append((event, data))
    return events


def test_stream_agent_turn_emits_sports_dispatch_activity_and_sources(monkeypatch):
    class FakeDispatcher:
        def maybe_handle(self, message, thread_id):
            return LiveAgentResult(
                handled=True,
                agent_name="SportsAgent",
                answer="Live sports answer",
                tools=["sports_agent", "web_search"],
                sources=[
                    {
                        "url": "https://www.formula1.com/en/latest/article/race-report",
                        "title": "Race report",
                        "snippet": "Winner and podium",
                        "domain": "formula1.com",
                    }
                ],
            )

    async def _async_noop(*args, **kwargs):
        return None

    monkeypatch.setattr(api, "_live_dispatcher", FakeDispatcher())
    monkeypatch.setattr(api, "_background_learn", _async_noop)
    monkeypatch.setattr(api.asyncio, "create_task", lambda coro: coro.close())

    async def _collect():
        chunks = []
        async for chunk in api._stream_agent_turn(
            clean_message="Who won the last F1 race?",
            active_thread_id="thread-1",
            model=None,
        ):
            chunks.append(chunk)
        return chunks

    events = _parse_sse(asyncio.run(_collect()))
    names = [name for name, _ in events]

    assert "activity" in names
    assert ("tool", json.dumps({"name": "sports_agent"})) in events
    source_payload = next(json.loads(data) for name, data in events if name == "source")
    assert source_payload["domain"] == "formula1.com"
    final = json.loads(next(data for name, data in events if name == "final"))
    assert final["answer"] == "Live sports answer"


def test_stream_agent_turn_emits_responses_style_events_for_sports_dispatch(monkeypatch):
    class FakeDispatcher:
        def maybe_handle(self, message, thread_id):
            return LiveAgentResult(
                handled=True,
                agent_name="SportsAgent",
                answer="Live sports answer",
                tools=["sports_agent", "web_search"],
                sources=[
                    {
                        "url": "https://www.formula1.com/en/latest/article/race-report",
                        "title": "Race report",
                        "snippet": "Winner and podium",
                        "domain": "formula1.com",
                    }
                ],
            )

    async def _async_noop(*args, **kwargs):
        return None

    monkeypatch.setattr(api, "_live_dispatcher", FakeDispatcher())
    monkeypatch.setattr(api, "_background_learn", _async_noop)
    monkeypatch.setattr(api.asyncio, "create_task", lambda coro: coro.close())

    async def _collect():
        chunks = []
        async for chunk in api._stream_agent_turn(
            clean_message="Who won the last F1 race?",
            active_thread_id="thread-1",
            model=None,
        ):
            chunks.append(chunk)
        return chunks

    events = _parse_sse(asyncio.run(_collect()))
    names = [name for name, _ in events]

    assert "response.created" in names
    assert "response.in_progress" in names
    assert "response.output_item.added" in names
    assert "response.output_text.delta" in names
    assert "response.completed" in names

    created = json.loads(next(data for name, data in events if name == "response.created"))
    assert created["type"] == "response.created"
    assert created["thread_id"] == "thread-1"
    assert created["response"]["status"] == "in_progress"

    added = [json.loads(data) for name, data in events if name == "response.output_item.added"]
    assert any(p["item"]["type"] == "subagent_call" and p["item"]["name"] == "SportsAgent" for p in added)
    assert any(p["item"]["type"] == "tool_call" and p["item"]["name"] == "web_search" for p in added)

    delta = json.loads(next(data for name, data in events if name == "response.output_text.delta"))
    assert delta["type"] == "response.output_text.delta"
    assert delta["delta"] == "Live sports answer"

    completed = json.loads(next(data for name, data in events if name == "response.completed"))
    assert completed["type"] == "response.completed"
    assert completed["response"]["status"] == "completed"
    assert completed["response"]["output_text"] == "Live sports answer"
    assert completed["response"]["tools"] == ["sports_agent", "web_search"]
    assert completed["response"]["sources"][0]["domain"] == "formula1.com"


def test_stream_agent_turn_marks_subagent_error_status(monkeypatch):
    class FakeDispatcher:
        def maybe_handle(self, message, thread_id):
            return LiveAgentResult(
                handled=True,
                agent_name="XAgent",
                answer="XAgent could not complete this request.",
                status="error",
                tools=["x_agent"],
            )

    async def _async_noop(*args, **kwargs):
        return None

    monkeypatch.setattr(api, "_live_dispatcher", FakeDispatcher())
    monkeypatch.setattr(api, "_background_learn", _async_noop)
    monkeypatch.setattr(api.asyncio, "create_task", lambda coro: coro.close())

    async def _collect():
        chunks = []
        async for chunk in api._stream_agent_turn(
            clean_message="What did NBA post on X?",
            active_thread_id="thread-1",
            model=None,
        ):
            chunks.append(chunk)
        return chunks

    events = _parse_sse(asyncio.run(_collect()))
    done_items = [json.loads(data)["item"] for name, data in events if name == "response.output_item.done"]

    assert any(item["type"] == "subagent_call" and item["status"] == "failed" for item in done_items)
