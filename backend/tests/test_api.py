from types import SimpleNamespace
import asyncio
import json
import sqlite3
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from langchain_core.messages import ToolMessage
import pytest

from agent import api
from agent.agents.live_dispatcher import LiveAgentResult
from agent.computer_use_runtime import ComputerUseRuntime


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


def _parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        event = "message"
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if data:
            events.append((event, json.loads(data)))
    return events


def test_health_endpoint_reports_service_and_vector_store(monkeypatch):
    monkeypatch.setattr(api, "_vector_health", lambda: {"ok": True, "collections": ["obsidian_vault"]})
    monkeypatch.setattr(api, "_embedding_health", lambda: {"ok": True, "provider": "sentence-transformers"})

    with TestClient(api.app) as client:
        response = client.get("/api/health?deep=true")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "personal-agent-api"
    assert body["vector"]["ok"] is True
    assert body["embeddings"]["ok"] is True
    assert body["models"]["primary"]


def test_health_endpoint_is_lightweight_by_default(monkeypatch):
    def fail_heavy_probe():
        raise AssertionError("lightweight health must not run heavy dependency probes")

    monkeypatch.setattr(api, "_vector_health", fail_heavy_probe)
    monkeypatch.setattr(api, "_embedding_health", fail_heavy_probe)

    with TestClient(api.app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["service"] == "personal-agent-api"
    assert body["checks"]["mode"] == "lightweight"
    assert "vector" not in body
    assert "embeddings" not in body


def test_capabilities_endpoint_publishes_stable_frontend_contract():
    with TestClient(api.app) as client:
        response = client.get("/api/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == "v1"
    assert body["contract_version"] == 1
    assert body["frontend"]["canonical_entry"] == "/design-uploads/Vellum%20Default%20Re-designed.html"

    features = body["features"]
    for key in ["chat", "plugins", "spotify", "memory_orchestrator", "knowledge_wiki", "hermes_skills", "openrouter", "agent_runtime"]:
        assert key in features
        assert isinstance(features[key]["enabled"], bool)
        assert features[key]["contract"] == "v1"
        assert features[key]["endpoints"]

    assert features["spotify"]["plugin_owned"] is True
    assert features["memory_orchestrator"]["plugin_owned"] is True
    assert features["hermes_skills"]["plugin_owned"] is True
    assert features["openrouter"]["endpoints"]["models"] == "/api/models"

    chat_events = body["stream_events"]["chat"]
    assert "response.output_text.delta" in chat_events
    assert "agent.activity" in chat_events
    assert "response.completed" in chat_events


def test_cors_allows_local_vite_fallback_ports():
    with TestClient(api.app) as client:
        response = client.options(
            "/api/computer-use/status",
            headers={
                "Origin": "http://127.0.0.1:5174",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"


def test_cors_allows_file_opened_default_ui():
    with TestClient(api.app) as client:
        response = client.options(
            "/api/chat/stream",
            headers={
                "Origin": "null",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "null"


def test_chat_endpoint_invokes_agent(monkeypatch, tmp_path):
    fake_agent = FakeAgent()
    runtime = ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )

    def fake_create_task(coro):
        coro.close()
        return object()

    monkeypatch.setattr(api, "agent", fake_agent)
    monkeypatch.setattr(api, "computer_use_runtime", runtime)
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


def test_chat_endpoint_passes_through_x_agent_result_without_model_rewrite(monkeypatch):
    class FakeDispatcher:
        def maybe_handle(self, message, thread_id):
            return LiveAgentResult(
                handled=True,
                agent_name="XAgent",
                status="answered",
                answer="[1] @openai: saved post\n    https://x.com/openai/status/1234567890123456789",
                tools=["x_agent"],
                sources=[
                    {
                        "url": "https://x.com/openai/status/1234567890123456789",
                        "title": "@openai on X",
                        "domain": "x.com",
                    }
                ],
            )

    class FailingAgent:
        async def ainvoke(self, *args, **kwargs):
            raise AssertionError("main model should not rewrite exact XAgent results")

    monkeypatch.setattr(api, "_live_dispatcher", FakeDispatcher())
    monkeypatch.setattr(api, "agent", FailingAgent())
    async def fake_background_learn(*args, **kwargs):
        return None

    monkeypatch.setattr(api, "_background_learn", fake_background_learn)

    with TestClient(api.app) as client:
        response = client.post("/api/chat", json={"message": "show my X bookmarks", "thread_id": "x-pass"})

    assert response.status_code == 200
    body = response.json()
    assert "https://x.com/openai/status/1234567890123456789" in body["answer"]
    assert body["tools"] == ["x_agent"]
    assert body["sources"][0]["url"] == "https://x.com/openai/status/1234567890123456789"


def test_chat_endpoint_passes_image_attachments_to_model_content(monkeypatch, tmp_path):
    fake_agent = FakeAgent()
    runtime = ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )

    def fake_create_task(coro):
        coro.close()
        return object()

    monkeypatch.setattr(api, "agent", fake_agent)
    monkeypatch.setattr(api, "computer_use_runtime", runtime)
    monkeypatch.setattr(api.asyncio, "create_task", fake_create_task)

    with TestClient(api.app) as client:
        response = client.post(
            "/api/chat",
            json={
                "message": "what can you see?",
                "thread_id": "frontend-image",
                "attachments": [
                    {
                        "name": "frame.png",
                        "kind": "image",
                        "mime_type": "image/png",
                        "data_url": "data:image/png;base64,iVBORw0KGgo=",
                    }
                ],
            },
        )

    assert response.status_code == 200
    content = fake_agent.calls[0][0]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "what can you see?"}
    assert content[1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}


def test_ui_conversation_endpoints_persist_sidebar_history(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_UI_CONVERSATIONS_PATH", tmp_path / "conversations.json")
    monkeypatch.setattr(api, "_index_ui_conversation", lambda conversation: {"indexed_turns": 1})
    monkeypatch.setattr(api, "_project_ui_conversation", lambda conversation: {"ok": True, "action": "update"})
    monkeypatch.setattr(api, "_archive_ui_conversation", lambda conversation: {"ok": True, "archived": True})

    payload = {
        "id": "chat-1",
        "thread_id": "thread-1",
        "title": "Sports question",
        "created": "Today",
        "pinned": False,
        "archived": False,
        "projectId": None,
        "messages": [
            {"id": "u1", "role": "user", "text": "When is the next NBA game?"},
            {"id": "a1", "role": "assistant", "text": "Live answer"},
        ],
    }

    with TestClient(api.app) as client:
        saved = client.put("/api/conversations/chat-1", json=payload)
        listed = client.get("/api/conversations")
        fetched = client.get("/api/conversations/chat-1")
        patched = client.patch("/api/conversations/chat-1", json={"pinned": True, "title": "Pinned sports"})
        deleted = client.delete("/api/conversations/chat-1")

    assert saved.status_code == 200
    assert listed.json()["conversations"][0]["title"] == "Sports question"
    assert fetched.json()["conversation"]["messages"][1]["text"] == "Live answer"
    assert patched.json()["conversation"]["pinned"] is True
    assert patched.json()["conversation"]["title"] == "Pinned sports"
    assert deleted.json()["ok"] is True
    assert deleted.json()["obsidian_projection"]["archived"] is True


def test_recent_conversation_context_is_injected_for_recall_questions(monkeypatch, tmp_path):
    fake_agent = FakeAgent()
    monkeypatch.setattr(api, "agent", fake_agent)
    monkeypatch.setattr(api, "_UI_CONVERSATIONS_PATH", tmp_path / "conversations.json")
    monkeypatch.setattr(api.asyncio, "create_task", lambda coro: coro.close() or object())
    (tmp_path / "conversations.json").write_text(
        json.dumps({
            "conversations": [
                {
                    "id": "chat-1",
                    "thread_id": "thread-1",
                    "title": "Today",
                    "messages": [
                        {"role": "user", "text": "We fixed Vellum streaming and X OAuth today."},
                        {"role": "assistant", "text": "Yes, the stream now completes correctly."},
                    ],
                }
            ]
        }),
        encoding="utf-8",
    )

    response = asyncio.run(api._run_agent("what did we talk about today?", thread_id="thread-1", model=None, attachments=[]))

    assert response.answer == "API fake answer"
    content = fake_agent.calls[0][0]["messages"][0]["content"]
    assert "Recent Vellum conversation context" in content
    assert "We fixed Vellum streaming and X OAuth today" in content


def test_memory_summary_saved_archived_and_dreaming_endpoints(monkeypatch, tmp_path):
    from agent.memory.fts5 import FTS5Memory
    from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
    from agent.memory.resolved import ResolvedQuestionsCache
    from agent.tools.capabilities.memory_service import MemoryCapabilityService

    store = SQLiteMemoryStore(tmp_path / "memory.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
        memory_dir=tmp_path / "memory-files",
    )
    store.update_global_summary("User is building Vellum.")
    saved_id = store.save_memory(kind="preference", text="User prefers concise answers.", source_thread_id="t1", confidence=0.9)
    archived_id = store.save_memory(kind="project", text="Old project memory.", source_thread_id="t1", confidence=0.7)
    store.archive(archived_id)
    monkeypatch.setattr(api, "_memory_orchestrator", orchestrator)

    with TestClient(api.app) as client:
        summary = client.get("/api/memory/summary")
        saved = client.get("/api/memory/saved")
        archived = client.get("/api/memory/archived")
        pinned = client.post(f"/api/memory/{saved_id}/pin", json={"pinned": True})
        dream = client.post("/api/memory/dreaming/run")
        status = client.get("/api/memory/dreaming/status")

    assert summary.status_code == 200
    assert summary.json()["global_summary"] == "User is building Vellum."
    assert saved.json()["memories"][0]["text"] == "User prefers concise answers."
    assert archived.json()["memories"][0]["id"] == archived_id
    assert pinned.json()["memory"]["pinned"] is True
    assert dream.json()["global_summary"]
    assert status.json()["status"] in {"idle", "completed"}


def test_memory_settings_endpoint_and_background_learning_gate(monkeypatch, tmp_path):
    from agent.memory.fts5 import FTS5Memory
    from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
    from agent.memory.resolved import ResolvedQuestionsCache
    from agent.tools.capabilities.memory_service import MemoryCapabilityService

    store = SQLiteMemoryStore(tmp_path / "memory.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
        memory_dir=tmp_path / "memory-files",
    )
    monkeypatch.setattr(api, "_memory_orchestrator", orchestrator)

    with TestClient(api.app) as client:
        before = client.get("/api/memory/settings")
        updated = client.post(
            "/api/memory/settings",
            json={"memory_enabled": False, "dreaming_enabled": False, "reference_history_enabled": False},
        )

    assert before.status_code == 200
    assert before.json()["settings"]["memory_enabled"] is True
    assert updated.status_code == 200
    assert updated.json()["settings"]["memory_enabled"] is False
    assert updated.json()["settings"]["dreaming_enabled"] is False
    assert updated.json()["settings"]["reference_history_enabled"] is False

    asyncio.run(
        api._background_learn(
            "Remember that I prefer concise answers.",
            "I will remember that.",
            thread_id="memory-off",
            source="api",
        )
    )

    assert store.list_pending() == []
    assert store.list_saved() == []


def test_background_learn_records_pending_memory_candidates(monkeypatch, tmp_path):
    from agent.memory.fts5 import FTS5Memory
    from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
    from agent.memory.resolved import ResolvedQuestionsCache
    from agent.tools.capabilities.memory_service import MemoryCapabilityService

    store = SQLiteMemoryStore(tmp_path / "memory.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
        memory_dir=tmp_path / "memory-files",
    )
    monkeypatch.setattr(api, "_memory_orchestrator", orchestrator)
    monkeypatch.setattr(
        api,
        "HonchoMemory",
        lambda **kwargs: SimpleNamespace(
            get_or_create_session=lambda thread_id: thread_id,
            add_message=lambda *args, **kwargs: None,
            chat=lambda **kwargs: "",
        ),
    )
    monkeypatch.setattr(api, "_project_context", lambda: SimpleNamespace(summarizer=lambda text: "", tick=lambda *args, **kwargs: None))

    asyncio.run(
        api._background_learn(
            "Remember that I prefer YouTube answers without Evidence sections.",
            "Understood.",
            thread_id="thread-1",
            source="api",
        )
    )

    assert "Evidence sections" in store.list_pending()[0]["text"]
    assert "Remember that I prefer" in orchestrator.fts5.recent_documents(limit=1)[0]["content"]


def test_background_learn_records_tool_backed_answers_as_resolved_memory(monkeypatch, tmp_path):
    from agent.memory.fts5 import FTS5Memory
    from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
    from agent.memory.resolved import ResolvedQuestionsCache
    from agent.tools.capabilities.memory_service import MemoryCapabilityService

    store = SQLiteMemoryStore(tmp_path / "memory.db")
    resolved = ResolvedQuestionsCache(tmp_path / "resolved.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=resolved,
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
        memory_dir=tmp_path / "memory-files",
    )
    monkeypatch.setattr(api, "_memory_orchestrator", orchestrator)
    monkeypatch.setattr(
        api,
        "HonchoMemory",
        lambda **kwargs: SimpleNamespace(
            get_or_create_session=lambda thread_id: thread_id,
            add_message=lambda *args, **kwargs: None,
            chat=lambda **kwargs: "",
        ),
    )
    monkeypatch.setattr(
        api,
        "_project_context",
        lambda: SimpleNamespace(summarizer=lambda text: "", tick=lambda *args, **kwargs: None),
    )

    asyncio.run(
        api._background_learn(
            "What happened in the Giannis trade to Miami?",
            "Milwaukee received Tyler Herro, Nikola Jovic, Jaime Jaquez Jr., and two first-round picks.",
            thread_id="trade-thread",
            source="api",
            tools=[{"name": "web_search", "output": {"answer": "Giannis trade package details"}}],
            sources=["https://example.com/giannis-miami"],
            confidence=0.93,
            agent_name="SportsAgent",
        )
    )

    with sqlite3.connect(resolved.db_path) as connection:
        stored = connection.execute("SELECT query, answer_summary FROM resolved_questions").fetchone()

    assert stored is not None
    assert "Giannis" not in stored[0]
    assert "Tyler Herro" not in stored[1]
    assert "Tyler Herro" in related["answer_summary"]


def test_background_learn_scopes_specialist_candidates_to_specialist(monkeypatch, tmp_path):
    from agent.memory.fts5 import FTS5Memory
    from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
    from agent.memory.resolved import ResolvedQuestionsCache
    from agent.tools.capabilities.memory_service import MemoryCapabilityService

    store = SQLiteMemoryStore(tmp_path / "memory.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
        memory_dir=tmp_path / "memory-files",
    )
    monkeypatch.setattr(api, "_memory_orchestrator", orchestrator)
    monkeypatch.setattr(
        api,
        "HonchoMemory",
        lambda **kwargs: SimpleNamespace(
            get_or_create_session=lambda thread_id: thread_id,
            add_message=lambda *args, **kwargs: None,
            chat=lambda **kwargs: "",
        ),
    )
    monkeypatch.setattr(api, "_project_context", lambda: SimpleNamespace(summarizer=lambda text: "", tick=lambda *args, **kwargs: None))

    asyncio.run(
        api._background_learn(
            "Remember that I prefer standings in sports answers.",
            "Understood.",
            thread_id="sports-memory",
            source="sports_agent",
            agent_name="SportsAgent",
        )
    )

    assert store.list_pending()[0]["scope"] == "agent:SportsAgent"


def test_agent_profiles_endpoint_exposes_safe_public_configuration(monkeypatch, tmp_path):
    from agent.profiles import ProfileRegistry

    monkeypatch.setattr(api, "_profile_registry", ProfileRegistry(profile_dir=tmp_path / "profiles"))

    with TestClient(api.app) as client:
        response = client.get("/api/agent-profiles")

    assert response.status_code == 200
    body = response.json()
    sports = next(profile for profile in body["profiles"] if profile["id"] == "SportsAgent")
    assert sports["executor"] == "deterministic"
    assert sports["memory"]["write_scope"] == "agent:SportsAgent"
    assert "instructions" not in sports
    assert "diagnostics" in body


def test_background_learn_auto_runs_dreaming_when_pending_threshold_met(monkeypatch, tmp_path):
    from agent.memory.fts5 import FTS5Memory
    from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
    from agent.memory.resolved import ResolvedQuestionsCache
    from agent.tools.capabilities.memory_service import MemoryCapabilityService

    store = SQLiteMemoryStore(tmp_path / "memory.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
        memory_dir=tmp_path / "memory-files",
    )
    monkeypatch.setattr(api, "_memory_orchestrator", orchestrator)
    monkeypatch.setattr(api, "_DREAMING_MIN_PENDING", 1)
    monkeypatch.setattr(api, "_DREAMING_COOLDOWN_SECONDS", 0)
    api._dreaming_status.clear()
    api._dreaming_status.update({"status": "idle", "last_run": None, "last_result": None})

    asyncio.run(
        api._background_learn(
            "Remember that I prefer concise Vellum demo answers.",
            "I will keep Vellum demo answers concise.",
            thread_id="thread-auto-dream",
            source="api",
        )
    )

    assert store.list_pending() == []
    assert any("concise Vellum demo answers" in item["text"] for item in store.list_saved())
    assert api._dreaming_status["status"] == "completed"
    assert api._dreaming_status["last_result"]["new_memories"]


def test_recent_conversation_context_scans_older_chats(monkeypatch, tmp_path):
    conversations_path = tmp_path / "conversations.json"
    conversations = []
    for index in range(12):
        messages = [
            {"role": "user", "text": f"old question {index}"},
            {"role": "assistant", "text": f"old answer {index}"},
        ]
        if index == 11:
            messages = [
                {"role": "user", "text": "Did Messi score a hat trick against Algeria?"},
                {"role": "assistant", "text": "Yes. Messi scored a hat-trick against Algeria."},
            ]
        conversations.append({"id": f"chat-{index}", "title": f"Chat {index}", "messages": messages})
    conversations_path.write_text(json.dumps({"conversations": conversations}), encoding="utf-8")
    monkeypatch.setattr(api, "_UI_CONVERSATIONS_PATH", conversations_path)

    context = api._recent_conversation_context("what did we say earlier about Messi Algeria?", "new-chat")

    assert "Chat 11" in context
    assert "Messi scored a hat-trick against Algeria" in context


def test_import_ui_conversations_indexes_older_chat_history(monkeypatch, tmp_path):
    from agent.memory.fts5 import FTS5Memory
    from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
    from agent.memory.resolved import ResolvedQuestionsCache
    from agent.tools.capabilities.memory_service import MemoryCapabilityService

    conversations_path = tmp_path / "conversations.json"
    conversations_path.write_text(
        json.dumps(
            {
                "conversations": [
                    {
                        "id": "old-sports-chat",
                        "title": "Messi Algeria",
                        "messages": [
                            {"role": "user", "text": "Tell me about Messi hat trick against Algeria."},
                            {"role": "assistant", "text": "Messi scored a hat-trick against Algeria in a 3-0 Argentina win."},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
        memory_dir=tmp_path / "memory-files",
    )
    monkeypatch.setattr(api, "_UI_CONVERSATIONS_PATH", conversations_path)
    monkeypatch.setattr(api, "_memory_orchestrator", orchestrator)

    imported = api._import_ui_conversations_to_memory()
    pack = orchestrator.build_context_pack(
        thread_id="new-chat",
        query="what happened with Messi and Algeria?",
        agent_name="SportsAgent",
    )

    assert imported["indexed_turns"] == 1
    assert pack["should_answer_from_memory"] is True
    assert "Messi scored a hat-trick against Algeria" in pack["context"]


def test_memory_crud_endpoints_create_update_pin_archive_and_delete(monkeypatch, tmp_path):
    from agent.memory.fts5 import FTS5Memory
    from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
    from agent.memory.resolved import ResolvedQuestionsCache
    from agent.tools.capabilities.memory_service import MemoryCapabilityService

    store = SQLiteMemoryStore(tmp_path / "memory.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
        memory_dir=tmp_path / "memory-files",
    )
    monkeypatch.setattr(api, "_memory_orchestrator", orchestrator)

    with TestClient(api.app) as client:
        created = client.post("/api/memory", json={"text": "User prefers memory controls to be editable.", "kind": "preference"})
        memory_id = created.json()["memory"]["id"]
        updated = client.post(f"/api/memory/{memory_id}/update", json={"text": "User prefers editable memory controls."})
        pinned = client.post(f"/api/memory/{memory_id}/pin", json={"pinned": True})
        unpinned = client.post(f"/api/memory/{memory_id}/pin", json={"pinned": False})
        archived = client.post(f"/api/memory/{memory_id}/archive")
        deleted = client.post(f"/api/memory/{memory_id}/delete")

    assert created.status_code == 200
    assert updated.json()["memory"]["text"] == "User prefers editable memory controls."
    assert pinned.json()["memory"]["pinned"] is True
    assert unpinned.json()["memory"]["pinned"] is False
    assert archived.json()["memory"]["status"] == "archived"
    assert deleted.json()["ok"] is True


def test_memory_summary_includes_indexed_conversation_context(monkeypatch, tmp_path):
    from agent.memory.fts5 import FTS5Memory
    from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
    from agent.memory.resolved import ResolvedQuestionsCache
    from agent.tools.capabilities.memory_service import MemoryCapabilityService

    conversations_path = tmp_path / "conversations.json"
    conversations_path.write_text(
        json.dumps(
            {
                "conversations": [
                    {
                        "id": "older-chat",
                        "title": "Messi Algeria",
                        "messages": [
                            {"role": "user", "text": "Did Messi score a hat trick against Algeria?"},
                            {"role": "assistant", "text": "Messi scored a hat-trick against Algeria in Argentina's opener."},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=SQLiteMemoryStore(tmp_path / "memory.db"),
        memory_dir=tmp_path / "memory-files",
    )
    monkeypatch.setattr(api, "_UI_CONVERSATIONS_PATH", conversations_path)
    monkeypatch.setattr(api, "_memory_orchestrator", orchestrator)
    api._import_ui_conversations_to_memory()

    with TestClient(api.app) as client:
        response = client.get("/api/memory/summary")

    body = response.json()
    assert response.status_code == 200
    assert body["recent_context"]
    assert "Messi scored a hat-trick against Algeria" in body["recent_context"][0]["content"]


def test_memory_recall_request_blocks_live_dispatch_for_chat_history(monkeypatch, tmp_path):
    conversations_path = tmp_path / "conversations.json"
    conversations_path.write_text(
        json.dumps(
            {
                "conversations": [
                    {
                        "id": "thread-memory",
                        "thread_id": "thread-memory",
                        "title": "Sports memory recall",
                        "messages": [
                            {"role": "user", "text": "no leave it i'm pretty sure we have spoken about fq as well"},
                            {"role": "assistant", "text": "I do not see fq in memory."},
                            {"role": "user", "text": "f1*"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "_UI_CONVERSATIONS_PATH", conversations_path)

    assert api._is_memory_recall_request("what about the f1 from my chats", "thread-memory") is True
    assert api._is_memory_recall_request("f1*", "thread-memory") is True


def test_recent_conversation_context_includes_indexed_memory_hits(monkeypatch, tmp_path):
    from agent.memory.fts5 import FTS5Memory
    from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
    from agent.memory.resolved import ResolvedQuestionsCache
    from agent.tools.capabilities.memory_service import MemoryCapabilityService

    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=SQLiteMemoryStore(tmp_path / "memory.db"),
        memory_dir=tmp_path / "memory-files",
    )
    orchestrator.fts5.add_document(
        content="Conversation: F1 recall\nQ: did i ask about f1?\nA: You asked who led Formula One standings.",
        thread_id="old-f1-chat",
        source_paths=["ui-conversation:old-f1-chat:1"],
    )
    orchestrator.fts5.add_document(
        content="Conversation: current bad recall\nQ: what about f1 from my chats\nA: Since you're asking now, here is the current state from web search.",
        thread_id="new-thread",
        source_paths=["ui-conversation:new-thread:1"],
    )
    monkeypatch.setattr(api, "_memory_orchestrator", orchestrator)
    monkeypatch.setattr(api, "_UI_CONVERSATIONS_PATH", tmp_path / "missing.json")

    context = api._recent_conversation_context("what about the f1 from my chats", "new-thread")

    assert "private memory/chat-recall context" in context
    assert "You asked who led Formula One standings" in context
    assert "current state from web search" not in context
    assert "do not use web_search, SerpAPI, SportsAgent" in context


def test_memory_orchestrator_search_returns_indexed_conversation_hits(monkeypatch, tmp_path):
    from agent.memory.fts5 import FTS5Memory
    from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
    from agent.memory.resolved import ResolvedQuestionsCache
    from agent.tools.capabilities.memory_service import MemoryCapabilityService
    from agent.tools import memory_orchestrator as memory_tool

    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=SQLiteMemoryStore(tmp_path / "memory.db"),
        memory_dir=tmp_path / "memory-files",
    )
    orchestrator.fts5.add_document(
        content="Conversation: F1 recall\nQ: Formula One\nA: User asked about F1 standings and next race.",
        thread_id="old-f1-chat",
        source_paths=["ui-conversation:old-f1-chat:1"],
    )
    monkeypatch.setattr(memory_tool, "_ORCHESTRATOR", orchestrator)

    result = json.loads(memory_tool.memory_orchestrator.invoke({"action": "search", "query": "f1 from my chats"}))

    assert result["ok"] is True
    assert result["indexed_conversation_hits"]
    assert "F1 standings" in result["indexed_conversation_hits"][0]["content"]


def test_provider_key_endpoint_persists_key_and_refreshes_models(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_env_path", lambda: tmp_path / ".env")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api.get_settings.cache_clear()
    from agent.llm.providers import get_provider_registry

    get_provider_registry.cache_clear()

    with TestClient(api.app) as client:
        before = client.get("/api/models")
        saved = client.post("/api/settings/provider-key", json={"provider": "openai", "api_key": "sk-test"})

    assert before.status_code == 200
    assert saved.status_code == 200
    assert saved.headers["Deprecation"] == "true"
    body = saved.json()
    assert body["provider_keys"]["openai"] is True
    assert any(item["provider"] == "openai" and not item["open_weights"] for item in body["models"])
    assert "OPENAI_API_KEY=sk-test" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_model_catalog_filters_cloud_models_by_configured_keys(monkeypatch):
    from agent.llm import providers

    monkeypatch.setattr(
        providers,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key="",
            openai_api_key="sk-openai",
            primary_model="google/gemma-4-31b-it",
        ),
    )

    models = providers.available_models()

    assert any(item.provider == "openai" and not item.open_weights for item in models)
    assert not any(item.provider == "anthropic" and not item.open_weights for item in models)


def test_ui_catalog_endpoints_expose_plugins_skills_automations_and_subagents(monkeypatch):
    monkeypatch.setattr(api, "mcp_health", lambda probe=False: {"mcp_servers": [{"name": "serpapi", "configured": True, "status": "probe_disabled"}]})
    monkeypatch.setattr(
        api,
        "agent_reach_plugin_status",
        lambda: SimpleNamespace(
            model_dump=lambda: {
                "id": "agent-reach",
                "name": "Agent-Reach",
                "type": "connector",
                "category": "Connectors",
                "configured": True,
                "status": "ready",
                "notes": "ready",
                "capabilities": ["x.search"],
            }
        ),
    )

    with TestClient(api.app) as client:
        plugins = client.get("/api/plugins")
        skills = client.get("/api/skills")
        automations = client.get("/api/automations")
        subagents = client.get("/api/subagents")

    assert plugins.status_code == 200
    plugin_ids = {item["id"] for item in plugins.json()["plugins"]}
    assert {"agent-reach", "serpapi"} <= plugin_ids
    memory_plugin = next(item for item in plugins.json()["plugins"] if item["id"] == "memory-orchestrator")
    assert memory_plugin["type"] == "system"
    assert memory_plugin["category"] == "Memory"
    assert memory_plugin["required"] is True
    assert "memory.run_dreaming" in memory_plugin["capabilities"]
    assert memory_plugin["metadata"]["portable_plugin"]["path"].endswith("plugins/memory/vellum-memory-orchestrator")
    agent_reach_plugin = next(item for item in plugins.json()["plugins"] if item["id"] == "agent-reach")
    assert agent_reach_plugin["metadata"]["portable_plugin"]["path"].endswith("plugins/connectors/agent-reach")
    assert skills.status_code == 200
    assert skills.json()["mock"] is False
    assert any(item["id"] == "skill-skill-creator-v1" for item in skills.json()["skills"]["active"])
    assert automations.status_code == 200
    assert any(item["id"] == "nightly-digest" for item in automations.json()["automations"])
    assert subagents.status_code == 200
    assert {"SportsAgent", "XAgent", "YoutubeAgent", "MemoryAgent"} <= {item["name"] for item in subagents.json()["subagents"]}


def test_skill_api_persists_actions_exposes_detail_and_builds_learn_prompt(monkeypatch, tmp_path):
    from agent.skills import SkillSurfaceService

    root = tmp_path / ".skills"
    proposed = root / "proposed" / "research" / "api-skill"
    proposed.mkdir(parents=True)
    (proposed / "SKILL.md").write_text(
        "---\nname: api-skill\ndescription: API skill\n---\n# API Skill\n\n## Procedure\nRun it.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api,
        "_skill_surface_singleton",
        SkillSurfaceService(root, logs_root=tmp_path / "logs", sources=[]),
    )
    async def no_skill_created(*_args, **_kwargs):
        return api.ChatResponse(answer="No mutation was created.", thread_id="skills-hub", tools=[])

    monkeypatch.setattr(api, "_run_agent", no_skill_created)

    with TestClient(api.app) as client:
        staged = client.post("/api/skills/action", json={"action": "approve", "name": "api-skill"})
        approved = client.post("/api/skills/action", json={"action": "pending_approve", "name": staged.json()["result"]["id"]})
        detail = client.get("/api/skills/api-skill")
        learned = client.post("/api/skills/learn", json={"source": "this conversation"})

    assert staged.status_code == 200
    assert staged.json()["result"]["status"] == "pending"
    assert approved.status_code == 200
    assert approved.json()["result"]["status"] == "applied"
    assert approved.json()["result"]["state"] == "active"
    assert detail.status_code == 200
    assert "Run it" in detail.json()["content"]
    assert learned.status_code == 422
    assert learned.json()["detail"]["code"] == "skill_not_staged"


def test_typed_skill_catalog_paginates_and_detail_exposes_skill_md(monkeypatch, tmp_path):
    from agent.skills import SkillCatalog, SkillManager, SkillSurfaceService

    root = tmp_path / ".skills"
    manager = SkillManager(root)
    for name in ("alpha-skill", "beta-skill"):
        manager.create(f"---\nname: {name}\ndescription: {name}\n---\n# {name}\n\n## Procedure\nRun safely.\n", confirm=True)
    surface = SkillSurfaceService(root, logs_root=tmp_path / "logs", sources=[])
    SkillCatalog(root).reconcile(embed_semantics=False)
    monkeypatch.setattr(api, "_skill_surface_singleton", surface)

    with TestClient(api.app) as client:
        first = client.get("/api/skills/v2/catalog", params={"limit": 1})
        second = client.get("/api/skills/v2/catalog", params={"limit": 1, "cursor": first.json()["next_cursor"]})
        cached = client.get("/api/skills/v2/catalog", params={"limit": 1}, headers={"If-None-Match": first.headers["etag"]})
        detail = client.get("/api/skills/alpha-skill")
        overview = client.get("/api/skills/v2/overview")

    assert first.status_code == 200
    assert first.headers["etag"]
    assert first.json()["items"][0]["normalized_name"] == "alpha-skill"
    assert second.json()["items"][0]["normalized_name"] == "beta-skill"
    assert cached.status_code == 304
    assert "name: alpha-skill" in detail.json()["skill_md"]
    assert detail.json()["provenance"]["source"] == "local"
    assert detail.json()["install_cli"] is None
    assert 'Use the installed "alpha-skill" skill' in detail.json()["prompt"]
    assert overview.json()["counts"]["active"] == 2


def test_x_oauth_callback_uses_persisted_flow_after_external_browser_return(monkeypatch, tmp_path):
    saved = {}

    class FakeXApiOauthModule:
        class secrets:
            @staticmethod
            def token_urlsafe(_length):
                return "state-token"

        @staticmethod
        def make_pkce_pair():
            return "verifier-token", "challenge-token"

        @staticmethod
        def build_authorize_url(client_id, redirect_uri, state, code_challenge):
            return (
                "https://x.com/i/oauth2/authorize"
                f"?client_id={client_id}&redirect_uri={redirect_uri}"
                f"&state={state}&code_challenge={code_challenge}"
            )

        @staticmethod
        def exchange_authorization_code(client_id, client_secret, code, redirect_uri, code_verifier, timeout_secs):
            saved["exchange"] = {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "timeout_secs": timeout_secs,
            }
            return {"access_token": "access", "refresh_token": "refresh"}

        @staticmethod
        def save_oauth_file(path, client_id, tokens):
            saved["path"] = path
            saved["client_id"] = client_id
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"client_id": client_id, "tokens": tokens}), encoding="utf-8")

    monkeypatch.setattr(api, "_load_script_module", lambda name: FakeXApiOauthModule)
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(
        x_api_client_id="client-id",
        x_api_client_secret="client-secret",
        x_tool_allow_private_reads=True,
        x_tool_allow_posts=True,
    ))
    monkeypatch.setattr(api, "_x_oauth_file", lambda provider: tmp_path / f"{provider}.json")
    monkeypatch.setattr(api, "_x_oauth_flow_path", lambda provider: tmp_path / f"{provider}-flow.json")

    with TestClient(api.app) as client:
        start = client.post("/api/x/oauth/start", json={"provider": "xapi"})
        assert start.status_code == 200
        state = parse_qs(urlparse(start.json()["authorize_url"]).query)["state"][0]

        api._oauth_flows.clear()
        callback = client.get(f"/api/x/oauth/callback/xapi?code=auth-code&state={state}")

    assert callback.status_code == 200
    assert "X OAuth complete" in callback.text
    assert saved["exchange"]["client_id"] == "client-id"
    assert saved["exchange"]["code_verifier"] == "verifier-token"
    assert (tmp_path / "xapi.json").exists()


def test_computer_use_mode_endpoints_toggle_state(monkeypatch, tmp_path):
    runtime = ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )
    monkeypatch.setattr(api, "computer_use_runtime", runtime)

    with TestClient(api.app) as client:
        enabled = client.post(
            "/api/computer-use/enable",
            json={"thread_id": "frontend", "source": "ui", "task": "find video stats"},
        )
        status = client.get("/api/computer-use/status")
        disabled = client.post("/api/computer-use/disable", json={"source": "ui"})

    assert enabled.status_code == 200
    assert enabled.json()["status"]["enabled"] is True
    assert enabled.json()["status"]["status"] == "ready"
    assert status.json()["enabled"] is True
    assert disabled.json()["status"]["enabled"] is False


def test_computer_use_workspace_action_records_event(monkeypatch, tmp_path):
    runtime = ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )
    calls = []

    class FakeWorker:
        def run(self, params):
            calls.append(params)
            return api.WorkspaceActionResult(
                action=params["action"],
                status="ok",
                message="workspace-ok",
                data={"seen": True},
            )

    monkeypatch.setattr(api, "computer_use_runtime", runtime)
    monkeypatch.setattr(api, "workspace_worker", FakeWorker())

    with TestClient(api.app) as client:
        response = client.post(
            "/api/computer-use/workspace/action",
            json={"action": "browser.navigate", "url": "https://example.com"},
        )

    assert response.status_code == 200
    body = response.json()
    assert calls == [{"action": "browser.navigate", "url": "https://example.com"}]
    assert body["status"] == "ok"
    assert body["message"] == "workspace-ok"
    assert body["data"] == {"seen": True}
    events = runtime.recent_events()
    assert events[-1]["kind"] == "workspace_action"
    assert events[-1]["data"]["action"] == "browser.navigate"


def test_computer_use_workspace_action_returns_400_for_invalid_action(monkeypatch):
    class FakeWorker:
        def run(self, params):
            raise api.WorkspaceActionError("bad workspace action")

    monkeypatch.setattr(api, "workspace_worker", FakeWorker())

    with TestClient(api.app) as client:
        response = client.post("/api/computer-use/workspace/action", json={"action": "wat"})

    assert response.status_code == 400
    assert response.json()["detail"] == "bad workspace action"


def test_workspace_api_accepts_core_milestone_actions(monkeypatch):
    seen = []

    class FakeResult:
        def __init__(self, action):
            self.action = action
            self.status = "ok"
            self.message = f"{action} ok"
            self.data = {"action": action}

    class FakeWorker:
        def run(self, params):
            seen.append(params["action"])
            return FakeResult(params["action"])

    monkeypatch.setattr(api, "workspace_worker", FakeWorker())
    actions = [
        {"action": "browser.open", "url": "https://example.com"},
        {"action": "browser.navigate", "url": "https://example.com/docs"},
        {"action": "input.click", "target": "button[name=Search]"},
        {"action": "input.type", "target": "input[name=q]", "text": "vellum"},
        {"action": "input.scroll", "amount": 1},
        {"action": "terminal.run", "command": "echo hello"},
        {"action": "screen.screenshot", "filename": "workspace.png"},
    ]

    with TestClient(api.app) as client:
        responses = [
            client.post("/api/computer-use/workspace/action", json=action)
            for action in actions
        ]

    assert [response.status_code for response in responses] == [200] * len(actions)
    assert seen == [action["action"] for action in actions]


def test_computer_use_session_start_and_stop(monkeypatch, tmp_path):
    runtime = ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )
    monkeypatch.setattr(api, "computer_use_runtime", runtime)
    overlay_calls = []

    class FakeOverlay:
        def start(self):
            overlay_calls.append("start")
            return "overlay started"

        def stop(self):
            overlay_calls.append("stop")
            return "overlay stopped"

        def status(self):
            return {"ready": overlay_calls[-1:] == ["start"]}

    monkeypatch.setattr(api, "_computer_use_overlay", lambda: FakeOverlay())

    with TestClient(api.app) as client:
        started = client.post("/api/computer-use/session/start", json={"source": "test", "thread_id": "frontend"})
        stopped = client.post("/api/computer-use/session/stop", json={"source": "test", "reason": "done"})

    assert started.status_code == 200
    assert started.json()["status"]["enabled"] is True
    assert stopped.status_code == 200
    assert stopped.json()["status"]["enabled"] is False
    assert overlay_calls == ["start", "stop"]


def test_computer_use_desktop_demo_endpoint_removed():
    with TestClient(api.app) as client:
        response = client.post("/api/computer-use/desktop/demo", json={"source": "test", "confirm": True})

    assert response.status_code == 404


def test_computer_use_session_task_records_instruction(monkeypatch, tmp_path):
    runtime = ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )
    runtime.enable(source="test")
    monkeypatch.setattr(api, "computer_use_runtime", runtime)

    class FakeOverlay:
        def start(self):
            return "overlay started"

        def stop(self):
            return "overlay stopped"

        def status(self):
            return {"ready": True}

    monkeypatch.setattr(api, "_computer_use_overlay", lambda: FakeOverlay())

    with TestClient(api.app) as client:
        response = client.post(
            "/api/computer-use/session/task",
            json={"source": "text", "thread_id": "frontend", "task": "open notepad"},
        )

    assert response.status_code == 200
    assert response.json()["result"]["status"] in {"queued", "done"}
    assert runtime.recent_events()[-1]["kind"] == "task_finished"


def test_computer_use_enable_starts_activity_overlay(monkeypatch, tmp_path):
    runtime = ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )
    monkeypatch.setattr(api, "computer_use_runtime", runtime)
    overlay_calls = []

    class FakeOverlay:
        def start(self):
            overlay_calls.append("start")
            return "overlay started"

        def stop(self):
            overlay_calls.append("stop")
            return "overlay stopped"

        def status(self):
            return {"ready": True}

    monkeypatch.setattr(api, "_computer_use_overlay", lambda: FakeOverlay())

    with TestClient(api.app) as client:
        response = client.post("/api/computer-use/enable", json={"source": "test"})

    assert response.status_code == 200
    assert overlay_calls == ["start"]
    assert runtime.recent_events()[-1]["kind"] == "session_started"


def test_computer_use_disable_stops_activity_overlay(monkeypatch, tmp_path):
    runtime = ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )
    runtime.enable(source="test")
    monkeypatch.setattr(api, "computer_use_runtime", runtime)
    overlay_calls = []

    class FakeOverlay:
        def start(self):
            overlay_calls.append("start")
            return "overlay started"

        def stop(self):
            overlay_calls.append("stop")
            return "overlay stopped"

        def status(self):
            return {"ready": False}

    monkeypatch.setattr(api, "_computer_use_overlay", lambda: FakeOverlay())

    with TestClient(api.app) as client:
        response = client.post("/api/computer-use/disable", json={"source": "test"})

    assert response.status_code == 200
    assert overlay_calls == ["stop"]
    assert runtime.recent_events()[-1]["kind"] == "session_stopped"


def test_chat_stream_intercepts_enable_computer_use_command(monkeypatch, tmp_path):
    class FailingAgent:
        async def astream_events(self, *args, **kwargs):
            raise AssertionError("computer use command should not call the agent")

    runtime = ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )
    learned = []

    async def fake_background_learn(query, answer, thread_id="default", source="agent"):
        learned.append((query, answer, thread_id, source))

    monkeypatch.setattr(api, "agent", FailingAgent())
    monkeypatch.setattr(api, "computer_use_runtime", runtime)
    monkeypatch.setattr(api, "_background_learn", fake_background_learn)

    class FakeOverlay:
        def start(self):
            return "overlay started"

        def stop(self):
            return "overlay stopped"

        def status(self):
            return {"ready": True}

    monkeypatch.setattr(api, "_computer_use_overlay", lambda: FakeOverlay())

    with TestClient(api.app) as client:
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"message": "enable computer use", "thread_id": "frontend"},
        ) as response:
            body = response.read().decode("utf-8")

    events = _parse_sse(body)
    names = [event for event, _payload in events]
    final_payload = next(payload for event, payload in events if event == "final")

    assert response.status_code == 200
    assert names[:3] == ["meta", "computer_use", "token"]
    assert final_payload["answer"].startswith("Computer use is on")
    assert runtime.status()["enabled"] is True
    assert learned == [("enable computer use", final_payload["answer"], "frontend", "computer_use")]


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


def test_chat_stream_passes_through_x_agent_result_without_model_rewrite(monkeypatch):
    class FakeDispatcher:
        def maybe_handle(self, message, thread_id):
            return LiveAgentResult(
                handled=True,
                agent_name="XAgent",
                status="answered",
                answer="[1] @openai: saved post\n    https://x.com/openai/status/1234567890123456789",
                tools=["x_agent"],
                sources=[
                    {
                        "url": "https://x.com/openai/status/1234567890123456789",
                        "title": "@openai on X",
                        "domain": "x.com",
                    }
                ],
                activity_events=[
                    {
                        "type": "tool_call_started",
                        "label": "Fetching X bookmarks with Agent-Reach...",
                        "name": "agent_reach_x_bookmarks",
                        "metadata": {"suppress_generic_tool": True},
                    }
                ],
            )

    class FailingStreamAgent:
        async def astream_events(self, *args, **kwargs):
            raise AssertionError("main model should not rewrite exact XAgent stream results")

    monkeypatch.setattr(api, "_live_dispatcher", FakeDispatcher())
    monkeypatch.setattr(api, "agent", FailingStreamAgent())
    async def fake_background_learn(*args, **kwargs):
        return None

    monkeypatch.setattr(api, "_background_learn", fake_background_learn)

    async def run_case():
        chunks = []
        async for chunk in api._stream_agent_turn(
            clean_message="show my X bookmarks",
            active_thread_id="x-stream-pass",
            model=None,
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run_case())
    events = _parse_sse("".join(chunks))

    text = "".join(
        data.get("delta", "")
        for event, data in events
        if event == "response.output_text.delta"
    )
    assert "https://x.com/openai/status/1234567890123456789" in text
    assert any(
        event == "agent.activity" and data["activity"]["label"] == "Fetching X bookmarks with Agent-Reach..."
        for event, data in events
    )


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

        class NoopLiveDispatcher:
            def maybe_handle(self, *args, **kwargs):
                return None

        monkeypatch.setattr(api, "_live_dispatcher", NoopLiveDispatcher())

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
