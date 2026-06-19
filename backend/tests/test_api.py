from types import SimpleNamespace
import asyncio
import json
from urllib.parse import parse_qs, urlparse

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
