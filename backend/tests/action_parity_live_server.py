"""Disposable backend for served-UI Action Parity checks; never a user profile."""

from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone
import asyncio
import os
import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse


def create_app() -> FastAPI:
    fixture = TemporaryDirectory(prefix="vellum-action-parity-")
    root = Path(fixture.name)
    os.environ["OPENROUTER_API_KEY"] = "action-parity-fixture-unused"
    os.environ["OBSIDIAN_VAULT_PATH"] = str(root / "vault")
    os.environ["FILESYSTEM_MCP_PATH"] = str(root / "vault")
    os.environ["KNOWLEDGE_CORE_DB_PATH"] = str(root / "knowledge.db")
    os.environ["KNOWLEDGE_BLOB_PATH"] = str(root / "blobs")
    (root / "vault").mkdir()

    from agent.app_actions import api as action_api
    from agent.app_actions.automations import AutomationActionService
    from agent.app_actions.lifecycle_controls import LifecycleControlError, PluginSkillActionService
    from agent.app_actions.models import AppActionContext
    from agent.app_actions.observability import ObservabilityActionService
    from agent.app_actions.runtime import AppActionRuntime
    from agent.app_actions.session_controls import SessionControlError
    from agent.conversations.lifecycle import ConversationLifecycle
    from agent.automations.store import AutomationStore
    from agent.plugins.registry import PluginRegistry

    lifecycle = ConversationLifecycle(path=root / "conversations.json")
    lifecycle.replace_all([{
        "id": "fixture-chat", "thread_id": "fixture-thread", "title": "Parity fixture chat",
        "messages": [], "model": "", "pinned": False, "archived": False,
    }])
    manifest = root / "plugins" / "connectors" / "parity-fixture" / "plugin.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "id: parity-fixture\nname: Parity Fixture\ntype: connector\n"
        "category: Connectors\ndescription: Disposable plugin for browser checks\n",
        encoding="utf-8",
    )
    plugin_registry = PluginRegistry(root / "plugins", state_path=root / "plugin-state.json")
    automation_store = AutomationStore(root / "automations")

    async def _fixture_run() -> dict:
        return {"status": "complete", "id": "fixture-run"}

    automation_actions = AutomationActionService(
        store_provider=lambda: automation_store,
        scheduler_available=lambda: True,
        mutation_notifier=lambda _automation_id: None,
        runner=lambda _automation, _store: _fixture_run(),
    )
    plugin_actions = PluginSkillActionService(
        plugin_registry=plugin_registry,
        skill_surface_provider=lambda: None,
        skill_hub_handler=lambda _payload: {},
        uninstall_handler=lambda _name: {},
    )

    def lifecycle_control(action_id: str, arguments: dict, context: AppActionContext, confirmed: bool) -> dict:
        if action_id != "plugin.state.set":
            raise LifecycleControlError("FIXTURE_ACTION_UNAVAILABLE", "Only fixture plugin state is supported.", unavailable=True)
        return plugin_actions.execute(action_id, arguments, context, confirmed=confirmed)

    def snapshot(period: str) -> dict:
        return {
            "schema_version": 1, "source": "fixture", "period": period,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "freshness": {"state": "ready"},
            "usage": {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0,
                      "cost_usd": 0, "calls": 0, "sessions": 0, "models": [], "daily": [], "recent": []},
            "runs": {"total": 0, "completed": 0, "failed": 0, "active": 0, "success_rate": 0},
            "recent_runs": [],
        }

    def session_control(action_id: str, arguments: dict, _context: AppActionContext) -> dict:
        if action_id != "agent.select":
            raise SessionControlError("FIXTURE_ACTION_UNAVAILABLE", "Fixture supports agent selection only.", unavailable=True)
        agent = str(arguments.get("agent") or arguments.get("agent_id") or "").removesuffix("Agent").lower()
        if agent not in {"books", "vellum"}:
            raise SessionControlError("FIXTURE_AGENT_UNAVAILABLE", "Fixture agent unavailable.", unavailable=True)
        return {
            "changed": True, "active_agent": "BooksAgent" if agent == "books" else "VellumAgent",
            "session_control_patch": {"agent_id": agent},
            "message": f"Fixture {agent} agent selected.",
        }

    runtime = AppActionRuntime(
        conversation_lifecycle=lifecycle,
        session_control_handler=session_control,
        lifecycle_control_handler=lifecycle_control,
        observability_handler=ObservabilityActionService(snapshot).execute,
        automation_handler=automation_actions.execute,
        plugin_registry=plugin_registry,
    )
    action_api.get_app_action_runtime = lambda: runtime

    app = FastAPI(title="Vellum Action Parity fixture")
    app.state.fixture = fixture  # Keep the disposable directory alive for this process.
    app.state.lifecycle = lifecycle
    app.state.automation_store = automation_store
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5176"],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(action_api.router, prefix="/api")

    @app.get("/api/conversations")
    @app.get("/api/conversations/library")
    def conversations() -> dict:
        return {"conversations": lifecycle.list()}

    @app.get("/api/conversations/{conversation_id}")
    def conversation(conversation_id: str) -> dict:
        return lifecycle.get(conversation_id)

    @app.get("/api/models")
    def models() -> dict:
        return {"models": []}

    @app.get("/api/settings")
    def settings() -> dict:
        return {}

    @app.get("/api/plugins")
    def plugins() -> dict:
        return {"plugins": plugin_registry.catalog()}

    @app.get("/api/skills/v2/catalog")
    def skills() -> dict:
        return {"items": []}

    @app.get("/api/automations")
    def automations() -> dict:
        return {"automations": automation_store.list()}

    @app.get("/api/subagents")
    def subagents() -> dict:
        return {"subagents": [{"id": "BooksAgent", "name": "BooksAgent", "description": "Disposable fixture agent", "enabled": True, "status": "available"}]}

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "models": {"primary": "Fixture (no model call)"}}

    @app.get("/api/observability/summary")
    def observability_summary(period: str = "7d") -> dict:
        return snapshot(period)

    @app.get("/api/observability/stream")
    async def observability_stream() -> StreamingResponse:
        async def events():
            yield 'event: observability.event\ndata: {"id":1,"type":"fixture_ready","label":"Disposable fixture"}\n\n'
            while True:
                await asyncio.sleep(20)
                yield ": fixture heartbeat\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/api/memory/summary")
    def memory_summary() -> dict:
        return {"global_summary": "", "saved_memories": [], "recent_context": []}

    @app.get("/api/memory/saved")
    @app.get("/api/memory/archived")
    def memory_entries() -> dict:
        return {"memories": []}

    @app.get("/api/memory/settings")
    def memory_settings() -> dict:
        return {"settings": {"memory_enabled": False, "dreaming_enabled": False}}

    @app.post("/api/chat/stream")
    async def fixture_chat_stream(request: Request) -> StreamingResponse:
        """Exercise the actual action planner/dispatcher without contacting an LLM."""

        payload = await request.json()
        submitted = str(payload.get("action_message") or payload.get("message") or "")
        turn = runtime.plan_submission(submitted)
        kind = "mixed" if turn.is_mixed else "action" if turn.actions else "conversation"
        context = AppActionContext.model_validate({
            **(payload.get("action_context") or {}),
            "source": "nlp",
            "invocation_conversation_id": str(payload.get("thread_id") or ""),
        })

        def events():
            def event(name: str, data: dict) -> str:
                return f"event: {name}\ndata: {json.dumps(data)}\n\n"

            for action, receipt in zip(turn.actions, runtime.dispatch_many(turn.actions, context)):
                yield event("app.action.requested", {"request": action.model_dump(mode="json"), "turn_kind": kind})
                yield event("app.action.receipt", {"receipt": receipt.model_dump(mode="json"), "turn_kind": kind})
            answer = f"Fixture response: {turn.conversation_message}" if turn.conversation_message else ""
            yield event("response.completed", {"response": {"thread_id": payload.get("thread_id") or "fixture-thread", "output_text": answer}})

        return StreamingResponse(events(), media_type="text/event-stream")

    return app
