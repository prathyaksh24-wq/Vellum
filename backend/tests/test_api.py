from types import SimpleNamespace

from fastapi.testclient import TestClient
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


def test_reindex_endpoint_returns_chunk_count(monkeypatch):
    class FakeIngester:
        def ingest(self, force=False):
            assert force is True
            return 7

    monkeypatch.setattr(api, "VaultIngester", FakeIngester)

    with TestClient(api.app) as client:
        response = client.post("/api/vault/reindex")

    assert response.status_code == 200
    assert response.json() == {"chunks": 7}


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
