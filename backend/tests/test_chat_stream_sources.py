"""Deterministic proof that the backend emits the source/activity SSE contract.

No network, no LLM, no model load. The agent's astream_events is replaced with a
synthetic v2 event generator and every heavy side-effecting dependency on the api
module is monkeypatched to an inert no-op. We then assert on the exact SSE strings
yielded by api._stream_agent_turn.
"""

from types import SimpleNamespace
import asyncio
import json

from langchain_core.messages import ToolMessage

from agent import api
from agent.tools.web import WEB_RESULT_SEPARATOR


# A realistic web_search-formatted output: two results, blocks joined by the
# separator web_search itself uses. The www. prefix on both domains must be
# stripped by extract_web_sources.
_RESULT_A = (
    "**Verstappen wins the last F1 race**\n"
    "Max Verstappen took victory in the season finale.\n"
    "https://www.formula1.com/en/latest/article/race-report"
)
_RESULT_B = (
    "**Full classification of the final Grand Prix**\n"
    "Norris and Leclerc completed the podium.\n"
    "https://www.skysports.com/f1/report/final-gp"
)
WEB_SEARCH_OUTPUT = WEB_RESULT_SEPARATOR.join([_RESULT_A, _RESULT_B])

URL_A = "https://www.formula1.com/en/latest/article/race-report"
URL_B = "https://www.skysports.com/f1/report/final-gp"


# ---------------------------------------------------------------------------
# (a) Helper-level test: _sources_from_messages + _activity_for
# ---------------------------------------------------------------------------


def test_sources_from_messages_parses_dedupes_and_strips_www():
    # Two distinct web_search ToolMessages plus a duplicate-url message; the
    # duplicate must collapse so only two Source objects survive.
    duplicate = ToolMessage(
        content=_RESULT_A,
        name="web_search",
        tool_call_id="call-dup",
    )
    primary = ToolMessage(
        content=WEB_SEARCH_OUTPUT,
        name="web_search",
        tool_call_id="call-1",
    )
    # A non-web_search message must be ignored entirely.
    noise = ToolMessage(
        content="**Ignore me**\nnot a search\nhttps://www.example.com/ignored",
        name="search_my_notes",
        tool_call_id="call-2",
    )

    sources = api._sources_from_messages([primary, duplicate, noise])

    assert len(sources) == 2
    assert all(isinstance(s, api.Source) for s in sources)

    by_url = {s.url: s for s in sources}
    assert set(by_url) == {URL_A, URL_B}

    assert by_url[URL_A].domain == "formula1.com"  # www. stripped
    assert by_url[URL_B].domain == "skysports.com"  # www. stripped
    assert by_url[URL_A].title == "Verstappen wins the last F1 race"
    assert "Verstappen" in by_url[URL_A].snippet
    assert by_url[URL_A].fetched_at  # populated via _now_iso()


def test_activity_for_web_search_label_and_detail():
    assert api._activity_for("web_search", {"query": "x"}) == ("Searched the web", "x")


# ---------------------------------------------------------------------------
# (b) Full-stream emission test for api._stream_agent_turn
# ---------------------------------------------------------------------------


def _parse_sse(chunks):
    """Turn the list of yielded SSE strings into [(event, data_str), ...]."""
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


class _FakeAgent:
    """Replaces the module-level agent: astream_events yields synthetic v2
    events in the order a real web_search turn would produce them."""

    async def astream_events(self, payload, config=None, version=None):
        # Tool starts -> drives 'tool' + 'activity' SSE.
        yield {
            "event": "on_tool_start",
            "name": "web_search",
            "data": {"input": {"query": "last f1 race"}},
        }
        # Tool ends -> drives 'source' SSE (one per unique url). Hand back a
        # ToolMessage carrying the formatted two-result string, exercising the
        # _tool_output_text(.content) path.
        yield {
            "event": "on_tool_end",
            "name": "web_search",
            "data": {
                "output": ToolMessage(
                    content=WEB_SEARCH_OUTPUT,
                    name="web_search",
                    tool_call_id="call-1",
                )
            },
        }
        # Model stream -> drives 'token' SSE and the final answer text.
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": SimpleNamespace(content="Verstappen won the last race.")},
        }

    async def aclose(self):
        return None


def _run_stream(monkeypatch):
    fake_agent = _FakeAgent()
    monkeypatch.setattr(api, "agent", fake_agent)
    monkeypatch.setattr(api._live_dispatcher, "maybe_handle", lambda message, thread_id: None)

    async def _async_noop(*args, **kwargs):
        return None

    # Neutralize every heavy/side-effecting dependency the generator touches.
    monkeypatch.setattr(api, "_ensure_model", _async_noop)
    monkeypatch.setattr(api, "_repair_incomplete_tool_history", _async_noop)
    monkeypatch.setattr(api, "_background_learn", _async_noop)
    monkeypatch.setattr(api, "capture_from_stream_event", lambda *a, **k: None)

    # asyncio.create_task(_background_learn(...)) is fired for a non-empty
    # answer; swallow the coroutine so no warning/leak occurs.
    def _fake_create_task(coro):
        coro.close()
        return SimpleNamespace()

    monkeypatch.setattr(api.asyncio, "create_task", _fake_create_task)

    # computer_use_runtime.status() must report disabled so no session submit
    # path runs. The default runtime is disabled; assert it to be explicit.
    assert api.computer_use_runtime.status().get("enabled") in (False, None)

    async def _collect():
        chunks = []
        async for chunk in api._stream_agent_turn(
            clean_message="last f1 race",
            active_thread_id="t-test",
            model=None,
        ):
            chunks.append(chunk)
        return chunks

    return asyncio.run(_collect())


def test_stream_agent_turn_emits_source_activity_contract(monkeypatch):
    chunks = _run_stream(monkeypatch)
    events = _parse_sse(chunks)
    names = [name for name, _ in events]

    # No error event leaked.
    assert "error" not in names, f"unexpected error event in {names}"

    # At least one activity event, carrying the web_search label + query detail.
    activity_payloads = [json.loads(data) for name, data in events if name == "activity"]
    assert len(activity_payloads) >= 1
    assert any(
        p.get("label") == "Searched the web" and p.get("detail") == "last f1 race"
        for p in activity_payloads
    )

    # A 'tool' event for web_search precedes the activity.
    assert ("tool", json.dumps({"name": "web_search"})) in events

    # One 'source' event per unique url (>= 2), each a structured record.
    source_payloads = [json.loads(data) for name, data in events if name == "source"]
    assert len(source_payloads) >= 2
    source_urls = {p["url"] for p in source_payloads}
    assert source_urls == {URL_A, URL_B}
    by_url = {p["url"]: p for p in source_payloads}
    assert by_url[URL_A]["domain"] == "formula1.com"
    assert by_url[URL_B]["domain"] == "skysports.com"

    # The 'final' payload JSON carries the same sources (>= 2) with url/domain.
    final_data = next(data for name, data in events if name == "final")
    final = json.loads(final_data)
    assert final["thread_id"] == "t-test"
    assert final["answer"] == "Verstappen won the last race."
    assert len(final["sources"]) >= 2
    final_by_url = {s["url"]: s for s in final["sources"]}
    assert set(final_by_url) == {URL_A, URL_B}
    assert final_by_url[URL_A]["domain"] == "formula1.com"
    assert final_by_url[URL_B]["domain"] == "skysports.com"
