"""HTTP API layer for the personal agent."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.cli.project_commands import (
    CommandResult,
    InvalidCommand,
    handle_project_command,
)
from agent.config import get_settings
from agent.graph.agent import agent
from agent.memory.fts5 import FTS5Memory
from agent.memory.honcho_client import HonchoMemory
from agent.memory.project_context import ProjectContext
from agent.obsidian.ingester import VaultIngester
from agent.obsidian.watcher import start_vault_watcher
from agent.privacy.classifier import DataClass, classify
from agent.privacy.scrubber import PrivacyScrubber
from agent.scheduler.digest import start_scheduler
from agent.telemetry.hooks import capture_from_invoke_result, capture_from_stream_event
from agent.telemetry.usage_ledger import UsageLedger
from agent.terminal.profiles import get_profile as get_terminal_profile
from agent.terminal.profiles import list_profiles as list_terminal_profiles
from agent.terminal.session import TerminalSessionManager
from agent.tools.obsidian_write import store_qa_pair

_api_ledger = UsageLedger(Path("data/memory/usage.db"))
_fts5_memory = FTS5Memory()
terminal_session_manager = TerminalSessionManager()

_project_context_singleton: ProjectContext | None = None


def _project_context() -> ProjectContext:
    global _project_context_singleton
    if _project_context_singleton is None:
        s = get_settings()
        _project_context_singleton = ProjectContext(vault_root=s.obsidian_vault_path)
    return _project_context_singleton


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str | None = None
    model: str | None = None  # OpenRouter model id; switches the active model for this turn + subsequent


class ChatResponse(BaseModel):
    answer: str
    thread_id: str
    tools: list[str] = Field(default_factory=list)


class ReindexResponse(BaseModel):
    chunks: int


class SetActiveModelRequest(BaseModel):
    model: str = Field(min_length=1)  # OpenRouter id or label (label resolved via registry.resolve)


class ActiveModelResponse(BaseModel):
    id: str
    label: str
    provider: str
    open_weights: bool


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = start_scheduler()
    watcher = start_vault_watcher()
    app.state.scheduler = scheduler
    app.state.vault_watcher = watcher
    try:
        yield
    finally:
        if watcher is not None:
            watcher.stop()
        if scheduler is not None:
            shutdown = getattr(scheduler, "shutdown", None)
            if shutdown is not None:
                shutdown(wait=False)
        close = getattr(agent, "aclose", None)
        if close is not None:
            await close()


app = FastAPI(title="Personal Agent API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4242", "http://127.0.0.1:4242", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(prefix="/api")


def _thread_config(thread_id: str | None) -> dict[str, dict[str, str]]:
    settings = get_settings()
    return {"configurable": {"thread_id": thread_id or settings.thread_id}}


def _message_content(message: Any) -> str:
    if message is None:
        return ""
    content = message.get("content", "") if isinstance(message, dict) else getattr(message, "content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts).strip()
    return str(content or "").strip()


def _tool_call_names(messages: list[Any]) -> list[str]:
    names: list[str] = []
    for message in messages:
        tool_calls = message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
        for call in tool_calls or []:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name:
                names.append(str(name))
    return names


async def _ensure_model(model: str | None) -> str | None:
    """If `model` is provided and differs from the current active model,
    switch the registry and invalidate the cached agent so it rebuilds.
    Returns the resolved model id (or None if no switch happened)."""
    if not model:
        return None
    from agent.llm.providers import get_provider_registry

    registry = get_provider_registry()
    current_id = registry.current_model().id
    if model == current_id:
        return current_id
    entry = registry.set_active(model)
    if entry.id != current_id:
        await agent.aclose()
    return entry.id


async def _run_agent(message: str, thread_id: str | None, model: str | None = None) -> ChatResponse:
    clean_message = message.strip()
    if not clean_message:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    active_thread_id = thread_id or get_settings().thread_id

    if clean_message.startswith("/project"):
        parts = clean_message.split()
        args = parts[1:]
        ctx = _project_context()
        try:
            result = handle_project_command(ctx, active_thread_id, args)
            answer = result.message
        except InvalidCommand as exc:
            answer = f"⚠ {exc}"
        return ChatResponse(answer=answer, thread_id=active_thread_id, tools=[])

    try:
        await _ensure_model(model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": clean_message}]},
        config=_thread_config(active_thread_id),
    )
    capture_from_invoke_result(
        ledger=_api_ledger,
        result=result,
        thread_id=active_thread_id,
        fallback_model=get_settings().primary_model,
        source="api",
    )
    messages = result.get("messages", []) if isinstance(result, dict) else []
    answer = _message_content(messages[-1] if messages else None) or "No response."
    tools = _tool_call_names(messages)

    if answer and "blocked for privacy" not in answer.casefold():
        asyncio.create_task(_background_learn(clean_message, answer, active_thread_id))

    return ChatResponse(answer=answer, thread_id=active_thread_id, tools=tools)


async def _background_learn(query: str, answer: str, thread_id: str = "default") -> None:
    try:
        data_class, _reason = classify(query)
        if data_class == DataClass.RED:
            return
        scrubber = PrivacyScrubber()
        clean_query = scrubber.scrub(query)[0] if data_class == DataClass.YELLOW else query
        clean_answer = scrubber.scrub(answer)[0] if data_class == DataClass.YELLOW else answer
        await asyncio.to_thread(store_qa_pair, clean_query, clean_answer)
        await asyncio.to_thread(_fts5_memory.add_qa_pair, query=clean_query, answer=clean_answer, thread_id=thread_id, source_paths=[])
        settings = get_settings()
        honcho = HonchoMemory(
            base_url=settings.honcho_base_url,
            app_id=settings.honcho_app_id,
            user_id=settings.honcho_user_id,
        )
        session_id = await asyncio.to_thread(honcho.get_or_create_session, thread_id)
        await asyncio.to_thread(honcho.add_message, session_id, content=clean_query, role="user")
        await asyncio.to_thread(honcho.add_message, session_id, content=clean_answer, role="assistant")
        try:
            from agent.memory.project_context import build_fast_summarizer
            ctx = _project_context()
            # Lazy-bind a real summarizer once per process (the default is a placeholder)
            current = getattr(ctx.summarizer, "__name__", "")
            if current == "_default_summarizer":
                ctx.summarizer = build_fast_summarizer()
            summary = (clean_query[:80] + "…") if len(clean_query) > 80 else clean_query
            await asyncio.to_thread(ctx.tick, thread_id, summary)
        except Exception:
            # Never let project bookkeeping break the response
            pass
    except Exception:
        return


def _qdrant_health() -> dict[str, Any]:
    settings = get_settings()
    client = None
    try:
        from qdrant_client import QdrantClient

        if settings.qdrant_local_path is not None:
            settings.qdrant_local_path.mkdir(parents=True, exist_ok=True)
            client = QdrantClient(path=str(settings.qdrant_local_path))
            mode = "local"
            location = str(settings.qdrant_local_path)
        else:
            client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port, timeout=2)
            mode = "server"
            location = f"{settings.qdrant_host}:{settings.qdrant_port}"

        collections = [collection.name for collection in client.get_collections().collections]
        return {"ok": True, "mode": mode, "location": location, "collections": collections}
    except Exception as exc:
        location = (
            str(settings.qdrant_local_path)
            if settings.qdrant_local_path is not None
            else f"{settings.qdrant_host}:{settings.qdrant_port}"
        )
        return {"ok": False, "mode": "local" if settings.qdrant_local_path is not None else "server", "location": location, "error": str(exc)}
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            close()


def _embedding_health() -> dict[str, Any]:
    try:
        import sentence_transformers  # noqa: F401

        return {"ok": True, "provider": "sentence-transformers"}
    except Exception as exc:
        return {"ok": False, "provider": "sentence-transformers", "error": str(exc)}


@router.get("/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "ok": True,
        "service": "personal-agent-api",
        "vault": {"path": str(settings.obsidian_vault_path), "exists": settings.obsidian_vault_path.exists()},
        "qdrant": _qdrant_health(),
        "embeddings": _embedding_health(),
        "models": {
            "primary": settings.primary_model,
            "fallback": settings.fallback_model,
            "fast": settings.fast_model,
        },
        "mcp": {
            "apify_url": settings.apify_mcp_url,
            "filesystem_path": str(settings.filesystem_mcp_path),
        },
    }


@router.get("/status")
async def status() -> dict[str, Any]:
    return await health()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await _run_agent(request.message, request.thread_id, request.model)


def _chunk_text(chunk: Any) -> str:
    if chunk is None:
        return ""
    content = chunk.get("content", "") if isinstance(chunk, dict) else getattr(chunk, "content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    clean_message = request.message.strip()
    if not clean_message:
        raise HTTPException(status_code=400, detail="message cannot be empty")
    active_thread_id = request.thread_id or get_settings().thread_id

    if clean_message.startswith("/project"):
        parts = clean_message.split()
        args = parts[1:]
        ctx = _project_context()
        try:
            result = handle_project_command(ctx, active_thread_id, args)
            msg = result.message
        except InvalidCommand as exc:
            msg = f"⚠ {exc}"

        final_response = ChatResponse(answer=msg, thread_id=active_thread_id, tools=[])

        async def single_event():
            yield f"event: meta\ndata: {json.dumps({'thread_id': active_thread_id})}\n\n"
            yield f"event: token\ndata: {json.dumps({'text': msg})}\n\n"
            yield f"event: final\ndata: {final_response.model_dump_json()}\n\n"

        return StreamingResponse(single_event(), media_type="text/event-stream")

    try:
        await _ensure_model(request.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def events():
        yield f"event: meta\ndata: {json.dumps({'thread_id': active_thread_id})}\n\n"
        answer_parts: list[str] = []
        tool_names: list[str] = []
        try:
            stream = agent.astream_events(
                {"messages": [{"role": "user", "content": clean_message}]},
                config=_thread_config(active_thread_id),
                version="v2",
            )
            async for event in stream:
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    text = _chunk_text(event.get("data", {}).get("chunk"))
                    if text:
                        answer_parts.append(text)
                        yield f"event: token\ndata: {json.dumps({'text': text})}\n\n"
                elif kind == "on_tool_start":
                    name = event.get("name") or ""
                    if name:
                        tool_names.append(str(name))
                        yield f"event: tool\ndata: {json.dumps({'name': name})}\n\n"
                capture_from_stream_event(
                    ledger=_api_ledger,
                    event=event,
                    thread_id=active_thread_id,
                    fallback_model=get_settings().primary_model,
                    source="api",
                )
            answer = "".join(answer_parts).strip() or "No response."
            response = ChatResponse(answer=answer, thread_id=active_thread_id, tools=tool_names)
            if answer and "blocked for privacy" not in answer.casefold():
                asyncio.create_task(_background_learn(clean_message, answer, active_thread_id))
            yield f"event: final\ndata: {response.model_dump_json()}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/vault/reindex", response_model=ReindexResponse)
async def reindex() -> ReindexResponse:
    try:
        chunks = await asyncio.to_thread(VaultIngester().ingest, True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ReindexResponse(chunks=chunks)


@router.get("/memory/recent")
async def recent_memory(limit: int = 15) -> dict[str, list[str]]:
    rows = await asyncio.to_thread(_fts5_memory.recent_documents, limit=limit)
    return {"facts": [row["content"] for row in rows]}


@router.get("/memory/entries")
async def recent_memory_entries(limit: int = 30) -> dict[str, list[dict[str, Any]]]:
    entries = await asyncio.to_thread(_fts5_memory.recent_documents, limit=limit)
    return {"entries": entries}


class PrivacyClassifyRequest(BaseModel):
    text: str = ""


@router.post("/privacy/classify")
async def privacy_classify(request: PrivacyClassifyRequest) -> dict[str, str]:
    data_class, reason = classify(request.text)
    return {"class": data_class.value, "reason": reason}


@router.get("/models")
async def list_models() -> dict[str, Any]:
    """Catalog the frontend reads on load to populate the model picker."""
    from agent.llm.providers import get_provider_registry

    registry = get_provider_registry()
    active = registry.current_model()
    return {
        "active": {
            "id": active.id,
            "label": active.label,
            "provider": active.provider,
            "open_weights": active.open_weights,
        },
        "groups": [
            {"key": g.key, "label": g.label, "default_id": g.default_id}
            for g in registry.list_groups()
        ],
        "models": [
            {
                "id": m.id,
                "label": m.label,
                "provider": m.provider,
                "context": m.context,
                "tier": m.tier,
                "open_weights": m.open_weights,
            }
            for m in registry.list_models()
        ],
    }


@router.get("/mcp/health")
async def mcp_health() -> dict[str, Any]:
    """Per-MCP-server configuration + reachability hint.

    Reports whether each server has its required env vars set. Does NOT
    invoke any MCP tool — calling them has side effects and rate-limit
    cost. To functionally probe a server, call its tool from a chat turn."""
    settings = get_settings()
    servers: list[dict[str, Any]] = []

    def _entry(name: str, configured: bool, url_or_cmd: str, notes: str = "") -> dict[str, Any]:
        return {"name": name, "configured": configured, "endpoint": url_or_cmd, "notes": notes}

    servers.append(_entry(
        "filesystem",
        configured=settings.filesystem_mcp_path.exists(),
        url_or_cmd=str(settings.filesystem_mcp_path),
        notes="Restricted to vault path; reads only.",
    ))
    servers.append(_entry(
        "apify",
        configured=bool(settings.apify_api_token) and settings.apify_mcp_url.startswith("http"),
        url_or_cmd=settings.apify_mcp_url,
        notes="amazon + youtube scrapers; requires APIFY_API_TOKEN.",
    ))
    servers.append(_entry(
        "playwright",
        configured=bool(settings.playwright_mcp_command),
        url_or_cmd=f"{settings.playwright_mcp_command} {settings.playwright_mcp_args}",
        notes=f"Mutations allowed: {settings.playwright_mcp_allow_mutations}.",
    ))
    servers.append(_entry(
        "github",
        configured=bool(settings.github_mcp_token or settings.github_pat),
        url_or_cmd=settings.github_mcp_url,
        notes=f"Writes: {settings.github_mcp_allow_writes}, destructive: {settings.github_mcp_allow_destructive}.",
    ))
    servers.append(_entry(
        "obsidian",
        configured=bool(settings.obsidian_api_key),
        url_or_cmd=settings.obsidian_mcp_url,
        notes=f"Writes: {settings.obsidian_mcp_allow_writes}, deletes: {settings.obsidian_mcp_allow_destructive}, commands: {settings.obsidian_mcp_allow_commands}.",
    ))
    servers.append(_entry(
        "context7",
        configured=settings.context7_mcp_url.startswith("http"),
        url_or_cmd=settings.context7_mcp_url,
        notes="Library docs lookup; CONTEXT7_API_KEY optional (anonymous works).",
    ))
    servers.append(_entry(
        "gitmcp",
        configured=settings.gitmcp_mcp_url.startswith("http"),
        url_or_cmd=settings.gitmcp_mcp_url,
        notes="Public GitHub repo docs/code; no auth.",
    ))
    servers.append(_entry(
        "context_mode",
        configured=bool(settings.context_mode_mcp_command),
        url_or_cmd=f"{settings.context_mode_mcp_command} {settings.context_mode_mcp_args}",
        notes="Sandboxed code execution + indexed retrieval; requires Node >=22.5.",
    ))

    # Adjacent services Vellum depends on
    qdrant = _qdrant_health()

    honcho_reachable = False
    try:
        import urllib.request
        req = urllib.request.Request(settings.honcho_base_url, method="HEAD")
        with urllib.request.urlopen(req, timeout=1):
            honcho_reachable = True
    except Exception:
        honcho_reachable = False

    return {
        "mcp_servers": servers,
        "qdrant": qdrant,
        "honcho": {
            "base_url": settings.honcho_base_url,
            "reachable": honcho_reachable,
            "notes": "Self-hosted via Docker; if down, identity-memory layer is dead but chat still works.",
        },
    }


@router.post("/settings/active-model", response_model=ActiveModelResponse)
async def set_active_model(request: SetActiveModelRequest) -> ActiveModelResponse:
    """Switch the runtime active model and invalidate the cached LangGraph agent
    so the next chat turn rebuilds with the new model."""
    from agent.llm.providers import get_provider_registry

    registry = get_provider_registry()
    current_id = registry.current_model().id
    try:
        entry = registry.set_active(request.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if entry.id != current_id:
        await agent.aclose()  # force rebuild on next invoke
    return ActiveModelResponse(
        id=entry.id,
        label=entry.label,
        provider=entry.provider,
        open_weights=entry.open_weights,
    )


@router.get("/settings")
async def public_settings() -> dict[str, Any]:
    settings = get_settings()
    return {
        "thread_id": settings.thread_id,
        "honcho_base_url": settings.honcho_base_url,
        "vault_path": str(settings.obsidian_vault_path),
        "agent_notes_folder": settings.agent_notes_folder,
        "primary_model": settings.primary_model,
        "fallback_model": settings.fallback_model,
        "fast_model": settings.fast_model,
        "apify_mcp_url": settings.apify_mcp_url,
        "qdrant_host": settings.qdrant_host,
        "qdrant_port": settings.qdrant_port,
        "qdrant_local_path": str(settings.qdrant_local_path) if settings.qdrant_local_path is not None else None,
        "enable_nightly_digest": settings.enable_nightly_digest,
        "enable_vault_watcher": settings.enable_vault_watcher,
    }


_SETUP_STATE_PATH = Path("data/memory/setup_state.json")


def _read_setup_state() -> dict[str, Any]:
    if not _SETUP_STATE_PATH.exists():
        return {}
    try:
        return json.loads(_SETUP_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_setup_state(payload: dict[str, Any]) -> None:
    _SETUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETUP_STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _setup_catalog() -> dict[str, Any]:
    """Catalog of provider/MCP entries the wizard merges with its own list.
       Mirrors agent/llm/providers.py and agent/mcp/client.py SERVER_RUNNERS."""
    from agent.llm.providers import get_provider_registry

    registry = get_provider_registry()
    groups = [
        {"key": g.key, "label": g.label, "default_id": g.default_id}
        for g in registry.list_groups()
    ]
    models = [
        {
            "id": m.id,
            "label": m.label,
            "provider": m.provider,
            "context": m.context,
            "tier": m.tier,
            "open_weights": m.open_weights,
        }
        for m in registry.list_models()
    ]
    settings = get_settings()
    mcp_builtin = [
        {
            "id": "builtin.filesystem",
            "label": "Filesystem",
            "category": "Built-in",
            "url": f"builtin://filesystem?root={settings.filesystem_mcp_path}",
            "scope": str(settings.filesystem_mcp_path),
            "enabled": True,
        },
        {
            "id": "builtin.apify",
            "label": "Apify",
            "category": "Built-in",
            "url": settings.apify_mcp_url,
            "scope": "amazon + youtube scrapers",
            "enabled": True,
        },
    ]
    return {"llm_groups": groups, "llm_models": models, "mcp_builtin": mcp_builtin}


@router.get("/setup/state")
async def setup_state_get() -> dict[str, Any]:
    """Return persisted wizard state (if any) plus the live backend catalog
       the wizard should merge with its own static list."""
    return {
        "state": _read_setup_state(),
        "catalog": _setup_catalog(),
    }


class SetupStateBody(BaseModel):
    state: dict[str, Any]


@router.post("/setup/state")
async def setup_state_post(body: SetupStateBody) -> dict[str, Any]:
    """Persist a snapshot of the wizard state. Called on every advance/blur."""
    _write_setup_state(body.state)
    return {"ok": True}


@router.post("/setup/complete")
async def setup_complete(body: SetupStateBody) -> dict[str, Any]:
    """Finalize the wizard. Writes the snapshot to setup_state.json with a
       completed_at marker. Provider keys are NOT written from here — the
       wizard's key-input phase writes to ~/.vellum/.env directly via the
       shell adapter when the real backend is mounted."""
    from datetime import datetime, timezone

    payload = dict(body.state)
    payload["completed_at"] = datetime.now(timezone.utc).isoformat()
    _write_setup_state(payload)
    return {"ok": True, "completed_at": payload["completed_at"]}


@router.get("/terminal/profiles")
async def terminal_profiles() -> dict[str, list[dict[str, object]]]:
    return {"profiles": [profile.to_public_dict() for profile in list_terminal_profiles()]}


@router.websocket("/terminal/ws")
async def terminal_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    session = None
    output_task: asyncio.Task[None] | None = None

    async def pump_output() -> None:
        assert session is not None
        while True:
            data = await session.read()
            if data is None:
                await websocket.send_json({"type": "exit", "code": 0})
                break
            await websocket.send_json({"type": "output", "data": data})

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            if msg_type == "start":
                profile_id = str(message.get("profile") or "powershell")
                profile = get_terminal_profile(profile_id)
                if profile is None:
                    await websocket.send_json({"type": "error", "message": f"Unknown terminal profile: {profile_id}"})
                    continue
                if not profile.available:
                    await websocket.send_json({"type": "error", "message": profile.reason or f"{profile.label} is unavailable."})
                    continue
                session = await terminal_session_manager.create(profile)
                cols = int(message.get("cols") or 120)
                rows = int(message.get("rows") or 32)
                await session.resize(cols, rows)
                await websocket.send_json({"type": "ready", "sessionId": session.id, "profile": profile.id})
                output_task = asyncio.create_task(pump_output())
            elif msg_type == "input" and session is not None:
                await session.write(str(message.get("data") or ""))
            elif msg_type == "resize" and session is not None:
                await session.resize(int(message.get("cols") or 120), int(message.get("rows") or 32))
            elif msg_type == "terminate":
                break
            else:
                await websocket.send_json({"type": "error", "message": "Terminal session is not ready."})
    except WebSocketDisconnect:
        return
    finally:
        if output_task is not None:
            output_task.cancel()
        if session is not None:
            await terminal_session_manager.terminate(session.id)


app.include_router(router)


@app.get("/health")
async def root_health() -> dict[str, Any]:
    return await health()
