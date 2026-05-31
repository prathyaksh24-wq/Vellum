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
