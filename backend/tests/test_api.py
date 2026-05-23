from types import SimpleNamespace
import asyncio

from fastapi.testclient import TestClient
from langchain_core.messages import ToolMessage
import pytest

from agent import api


@pytest.fixture(autouse=True)
def disable_runtime_services(monkeypatch):
    monkeypatch.setattr(api, "start_scheduler", lambda: None)
    monkeypatch.setattr(api, "start_vault_watcher", lambda: None)


class FakeAgent:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, payload, config=None):
        self.calls.append((payload, config))
        message = SimpleNamespace(content="API fake answer", tool_calls=[{"name": "search_my_notes"}])
        return {"messages": [message]}

    async def aclose(self):
        return None


def test_health_endpoint_reports_service_and_qdrant(monkeypatch):
    monkeypatch.setattr(api, "_qdrant_health", lambda: {"ok": True, "collections": ["obsidian_vault"]})
    monkeypatch.setattr(api, "_embedding_health", lambda: {"ok": True, "provider": "sentence-transformers"})

    with TestClient(api.app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "personal-agent-api"
    assert body["qdrant"]["ok"] is True
    assert body["embeddings"]["ok"] is True
    assert body["models"]["primary"]


def test_chat_endpoint_invokes_agent(monkeypatch):
    fake_agent = FakeAgent()

    def fake_create_task(coro):
        coro.close()
        return object()

    monkeypatch.setattr(api, "agent", fake_agent)
    monkeypatch.setattr(api.asyncio, "create_task", fake_create_task)

    with TestClient(api.app) as client:
        response = client.post("/api/chat", json={"message": "hello", "thread_id": "frontend"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "API fake answer"
    assert body["thread_id"] == "frontend"
    assert body["tools"] == ["search_my_notes"]
    assert fake_agent.calls[0][0]["messages"][0]["content"] == "hello"
    assert fake_agent.calls[0][1]["configurable"]["thread_id"] == "frontend"


def test_chat_repairs_pending_tool_calls_before_next_turn(monkeypatch):
    class RepairingAgent:
        def __init__(self):
            self.events = []

        async def aget_state(self, config):
            self.events.append(("get_state", config["configurable"]["thread_id"]))
            return SimpleNamespace(
                values={
                    "messages": [
                        SimpleNamespace(
                            content="",
                            tool_calls=[
                                {
                                    "name": "browser_tabs",
                                    "args": {"action": "new", "url": "https://docs.google.com"},
                                    "id": "call-browser-tabs",
                                }
                            ],
                        )
                    ]
                }
            )

        async def aupdate_state(self, config, values):
            self.events.append(("update_state", config["configurable"]["thread_id"], values))

        async def ainvoke(self, payload, config=None):
            self.events.append(("ainvoke", config["configurable"]["thread_id"]))
            return {"messages": [SimpleNamespace(content="recovered", tool_calls=[])]}

    fake_agent = RepairingAgent()
    monkeypatch.setattr(api, "agent", fake_agent)
    monkeypatch.setattr(api.asyncio, "create_task", lambda coro: coro.close() or object())

    response = asyncio.run(api._run_agent("continue", thread_id="frontend"))

    assert response.answer == "recovered"
    assert fake_agent.events[0] == ("get_state", "frontend")
    assert fake_agent.events[1][0] == "update_state"
    repaired_messages = fake_agent.events[1][2]["messages"]
    assert len(repaired_messages) == 1
    assert isinstance(repaired_messages[0], ToolMessage)
    assert repaired_messages[0].tool_call_id == "call-browser-tabs"
    assert "browser_tabs" in repaired_messages[0].content
    assert fake_agent.events[2] == ("ainvoke", "frontend")


def test_stream_repairs_pending_tool_calls_after_mid_turn_error(monkeypatch):
    class FailingStreamAgent:
        def __init__(self):
            self.state_reads = 0
            self.repairs = []

        async def aget_state(self, config):
            self.state_reads += 1
            messages = []
            if self.state_reads > 1:
                messages = [
                    SimpleNamespace(
                        content="",
                        tool_calls=[
                            {
                                "name": "browser_tabs",
                                "args": {"action": "close", "index": "2"},
                                "id": "call-close-tab",
                            }
                        ],
                    )
                ]
            return SimpleNamespace(values={"messages": messages})

        async def aupdate_state(self, config, values):
            self.repairs.append(values)

        async def astream_events(self, *args, **kwargs):
            yield {"event": "on_tool_start", "name": "browser_tabs"}
            raise RuntimeError("tool node failed")

    fake_agent = FailingStreamAgent()
    monkeypatch.setattr(api, "agent", fake_agent)

    async def run_case():
        chunks = []
        async for chunk in api._stream_agent_turn(
            clean_message="open tabs",
            active_thread_id="frontend",
            model=None,
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run_case())

    assert any("event: error" in chunk for chunk in chunks)
    assert len(fake_agent.repairs) == 1
    repaired_messages = fake_agent.repairs[0]["messages"]
    assert isinstance(repaired_messages[0], ToolMessage)
    assert repaired_messages[0].tool_call_id == "call-close-tab"


def test_reindex_endpoint_returns_chunk_count(monkeypatch):
    class FakeIngester:
        def ingest(self, force=False):
            assert force is True
            return 7

    monkeypatch.setattr(api, "VaultIngester", FakeIngester)
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(enable_vector_search=True))

    with TestClient(api.app) as client:
        response = client.post("/api/vault/reindex")

    assert response.status_code == 200
    assert response.json() == {"chunks": 7}


def test_reindex_endpoint_rejects_when_vector_search_disabled(monkeypatch):
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(enable_vector_search=False))

    with TestClient(api.app) as client:
        response = client.post("/api/vault/reindex")

    assert response.status_code == 409


def test_api_lifespan_starts_and_stops_scheduler_and_watcher(monkeypatch):
    events = []

    class FakeScheduler:
        def shutdown(self, wait=False):
            events.append(("scheduler_shutdown", wait))

    class FakeWatcher:
        def stop(self):
            events.append(("watcher_stop", None))

    monkeypatch.setattr(api, "start_scheduler", lambda: events.append(("scheduler_start", None)) or FakeScheduler())
    monkeypatch.setattr(api, "start_vault_watcher", lambda: events.append(("watcher_start", None)) or FakeWatcher())

    with TestClient(api.app) as client:
        response = client.get("/api/status")

    assert response.status_code == 200
    assert events == [
        ("scheduler_start", None),
        ("watcher_start", None),
        ("watcher_stop", None),
        ("scheduler_shutdown", False),
    ]


def test_active_model_switch_waits_for_active_stream(monkeypatch):
    async def run_case():
        from agent.llm import providers as providers_mod

        providers_mod.get_provider_registry.cache_clear()
        api._agent_runtime_lock = asyncio.Lock()

        class StreamingAgent:
            def __init__(self):
                self.started = asyncio.Event()
                self.finish = asyncio.Event()
                self.streaming = False
                self.closed_while_streaming = False

            async def astream_events(self, *args, **kwargs):
                self.streaming = True
                self.started.set()
                yield {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content="ok")}}
                await self.finish.wait()
                self.streaming = False

            async def aclose(self):
                if self.streaming:
                    self.closed_while_streaming = True

        streaming_agent = StreamingAgent()
        monkeypatch.setattr(api, "agent", streaming_agent)
        async def fake_background_learn(*args, **kwargs):
            return None

        monkeypatch.setattr(api, "_background_learn", fake_background_learn)

        response = await api.chat_stream(api.ChatRequest(
            message="hello",
            thread_id="stream-lock-test",
            model="google/gemma-4-31b-it",
        ))

        async def consume_response():
            async for _chunk in response.body_iterator:
                pass

        consume_task = asyncio.create_task(consume_response())
        await asyncio.wait_for(streaming_agent.started.wait(), timeout=1)

        switch_task = asyncio.create_task(api.set_active_model(
            api.SetActiveModelRequest(model="deepseek/deepseek-v4-pro")
        ))
        await asyncio.sleep(0.05)

        assert not switch_task.done()
        assert streaming_agent.closed_while_streaming is False

        streaming_agent.finish.set()
        await asyncio.wait_for(consume_task, timeout=1)
        await asyncio.wait_for(switch_task, timeout=1)

        assert streaming_agent.closed_while_streaming is False
        providers_mod.get_provider_registry.cache_clear()

    asyncio.run(run_case())
