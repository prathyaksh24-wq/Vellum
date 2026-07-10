import asyncio
import json

from agent import api
from agent.agents.live_dispatcher import LiveAgentResult


def test_run_agent_uses_live_dispatcher_as_context_for_main_agent(monkeypatch):
    calls = []

    async def _natural_answer(payload, config=None):
        calls.append((payload, config))
        return {"messages": [type("Msg", (), {"content": "Natural Vellum answer.", "tool_calls": []})()]}

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

    async def _async_noop(*args, **kwargs):
        return None

    monkeypatch.setattr(api, "_live_dispatcher", FakeDispatcher())
    monkeypatch.setattr(api.agent, "ainvoke", _natural_answer)
    monkeypatch.setattr(api, "_ensure_model", _async_noop)
    monkeypatch.setattr(api, "_repair_incomplete_tool_history", _async_noop)
    monkeypatch.setattr(api.asyncio, "create_task", lambda coro: coro.close())

    response = asyncio.run(api._run_agent("NBA Finals update", "thread-1", None))

    assert response.answer == "Natural Vellum answer."
    assert response.thread_id == "thread-1"
    assert response.tools == ["sports_agent", "web_search"]
    assert response.sources[0].url == "https://www.nba.com/news/finals"
    assert "Sports Pupil answer" in calls[0][0]["messages"][0]["content"]


def test_run_agent_includes_specialist_snippets_and_fact_priority(monkeypatch):
    calls = []

    async def _natural_answer(payload, config=None):
        calls.append((payload, config))
        return {"messages": [type("Msg", (), {"content": "The next F1 race is the Austrian Grand Prix.", "tool_calls": []})()]}

    class FakeDispatcher:
        def maybe_handle(self, message, thread_id):
            return LiveAgentResult(
                handled=True,
                agent_name="SportsAgent",
                answer="SportsAgent found the next race in fresh public sources.",
                tools=["sports_agent", "web_search"],
                sources=[
                    {
                        "url": "https://www.formula1.com/en/racing/2026",
                        "title": "F1 calendar",
                        "snippet": "The next race is the Austrian Grand Prix at Red Bull Ring, not Monaco.",
                        "domain": "formula1.com",
                    }
                ],
            )

    async def _async_noop(*args, **kwargs):
        return None

    monkeypatch.setattr(api, "_live_dispatcher", FakeDispatcher())
    monkeypatch.setattr(api.agent, "ainvoke", _natural_answer)
    monkeypatch.setattr(api, "_ensure_model", _async_noop)
    monkeypatch.setattr(api, "_repair_incomplete_tool_history", _async_noop)
    monkeypatch.setattr(api.asyncio, "create_task", lambda coro: coro.close())

    response = asyncio.run(api._run_agent("What is the next F1 race?", "thread-1", None))

    prompt = calls[0][0]["messages"][0]["content"]
    assert response.answer == "The next F1 race is the Austrian Grand Prix."
    assert "The next race is the Austrian Grand Prix at Red Bull Ring, not Monaco." in prompt
    assert "treat the specialist result and source snippets as authoritative" in prompt.lower()


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


def test_stream_agent_turn_emits_sports_dispatch_then_main_agent_answer(monkeypatch):
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

    class FakeAgent:
        async def astream_events(self, payload, config=None, version=None):
            assert "Live sports answer" in payload["messages"][0]["content"]
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "Natural streamed answer."})()},
            }

    monkeypatch.setattr(api, "_live_dispatcher", FakeDispatcher())
    monkeypatch.setattr(api, "agent", FakeAgent())
    monkeypatch.setattr(api, "_ensure_model", _async_noop)
    monkeypatch.setattr(api, "_repair_incomplete_tool_history", _async_noop)
    monkeypatch.setattr(api, "_background_learn", _async_noop)
    monkeypatch.setattr(api, "capture_from_stream_event", lambda *a, **k: None)
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
    assert final["answer"] == "Natural streamed answer."


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

    class FakeAgent:
        async def astream_events(self, payload, config=None, version=None):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "Natural streamed answer."})()},
            }

    monkeypatch.setattr(api, "_live_dispatcher", FakeDispatcher())
    monkeypatch.setattr(api, "agent", FakeAgent())
    monkeypatch.setattr(api, "_ensure_model", _async_noop)
    monkeypatch.setattr(api, "_repair_incomplete_tool_history", _async_noop)
    monkeypatch.setattr(api, "_background_learn", _async_noop)
    monkeypatch.setattr(api, "capture_from_stream_event", lambda *a, **k: None)
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
    assert delta["delta"] == "Natural streamed answer."

    completed = json.loads(next(data for name, data in events if name == "response.completed"))
    assert completed["type"] == "response.completed"
    assert completed["response"]["status"] == "completed"
    assert completed["response"]["output_text"] == "Natural streamed answer."
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

    class FakeAgent:
        async def astream_events(self, payload, config=None, version=None):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "I could not complete the X lookup, but I can keep helping."})()},
            }

    monkeypatch.setattr(api, "_live_dispatcher", FakeDispatcher())
    monkeypatch.setattr(api, "agent", FakeAgent())
    monkeypatch.setattr(api, "_ensure_model", _async_noop)
    monkeypatch.setattr(api, "_repair_incomplete_tool_history", _async_noop)
    monkeypatch.setattr(api, "_background_learn", _async_noop)
    monkeypatch.setattr(api, "capture_from_stream_event", lambda *a, **k: None)
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


def test_stream_agent_turn_times_out_silent_model_stream(monkeypatch):
    class SilentAgent:
        async def astream_events(self, payload, config=None, version=None):
            await asyncio.sleep(1)
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "too late"})()},
            }

    async def _async_noop(*args, **kwargs):
        return None

    class Settings:
        llm_stream_timeout_seconds = 0.01

    monkeypatch.setattr(api, "agent", SilentAgent())
    monkeypatch.setattr(api._live_dispatcher, "maybe_handle", lambda message, thread_id: None)
    monkeypatch.setattr(api, "_ensure_model", _async_noop)
    monkeypatch.setattr(api, "_repair_incomplete_tool_history", _async_noop)
    monkeypatch.setattr(api, "get_settings", lambda: Settings())

    async def _collect():
        chunks = []
        async for chunk in api._stream_agent_turn(
            clean_message="hello",
            active_thread_id="thread-timeout",
            model=None,
            store=False,
        ):
            chunks.append(chunk)
        return chunks

    events = _parse_sse(asyncio.run(_collect()))

    assert any(name == "error" and "timed out" in data for name, data in events)
