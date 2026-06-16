from types import SimpleNamespace
import asyncio
import json

from fastapi.testclient import TestClient
from langchain_core.messages import ToolMessage
import pytest

from agent import api
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
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "personal-agent-api"
    assert body["vector"]["ok"] is True
    assert body["embeddings"]["ok"] is True
    assert body["models"]["primary"]


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


def test_ui_conversation_endpoints_persist_sidebar_history(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_UI_CONVERSATIONS_PATH", tmp_path / "conversations.json")

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
    assert deleted.json() == {"ok": True}


def test_ui_catalog_endpoints_expose_plugins_skills_automations_and_subagents(monkeypatch):
    monkeypatch.setattr(api, "mcp_health", lambda probe=False: {"mcp_servers": [{"name": "serpapi", "configured": True, "status": "probe_disabled"}]})

    with TestClient(api.app) as client:
        plugins = client.get("/api/plugins")
        skills = client.get("/api/skills")
        automations = client.get("/api/automations")
        subagents = client.get("/api/subagents")

    assert plugins.status_code == 200
    assert plugins.json()["plugins"][0]["id"] == "serpapi"
    assert skills.status_code == 200
    assert any(item["id"] == "sports-snapshot-brief" for item in skills.json()["skills"]["proposed"])
    assert automations.status_code == 200
    assert any(item["id"] == "nightly-digest" for item in automations.json()["automations"])
    assert subagents.status_code == 200
    assert {"SportsAgent", "XAgent", "YoutubeAgent", "MemoryAgent"} <= {item["name"] for item in subagents.json()["subagents"]}


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
