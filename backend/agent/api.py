"""HTTP API layer for the personal agent."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import importlib.util
import inspect
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, Field

from agent.cli.project_commands import (
    CommandResult,
    InvalidCommand,
    handle_project_command,
)
from agent.coding.events import event_payload, sse as coding_sse
from agent.coding.models import AccessMode, CodingSession, CodingSessionCreate, ProviderName
from agent.coding.service import CodingServiceError, CodingSessionService
from agent.computer_use.overlay import DesktopActivityOverlay
from agent.computer_use.session import ComputerUseSession, ComputerUseSessionError, NoopOverlay
from agent.computer_use_runtime import computer_use_runtime
from agent.computer_use_workspace import WorkspaceActionError, WorkspaceActionResult, workspace_worker
from agent.config import REPO_ROOT, get_settings
from agent.agents.live_dispatcher import LiveAgentDispatcher
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
from agent.voice.stt import get_stt_engine
from agent.voice.tts import get_tts_engine

_api_ledger = UsageLedger(Path("data/memory/usage.db"))
_fts5_memory = FTS5Memory()
terminal_session_manager = TerminalSessionManager()
coding_service = CodingSessionService()
_agent_runtime_lock = asyncio.Lock()
_live_dispatcher = LiveAgentDispatcher(vault_root=get_settings().obsidian_vault_path)
_oauth_flows: dict[str, dict[str, Any]] = {}

_project_context_singleton: ProjectContext | None = None


def _project_context() -> ProjectContext:
    global _project_context_singleton
    if _project_context_singleton is None:
        s = get_settings()
        _project_context_singleton = ProjectContext(vault_root=s.obsidian_vault_path)
    return _project_context_singleton


def _load_script_module(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load script {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str | None = None
    model: str | None = None  # OpenRouter model id; switches the active model for this turn + subsequent
    voice: bool = False
    store: bool = True  # when False, answer the turn but do NOT persist it (FTS5/Honcho/vault); log an audit breadcrumb instead


class Source(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    domain: str = ""
    fetched_at: str = ""
    source_index: int = 0
    source_type: str = ""
    favicon_url: str = ""
    provider_label: str = ""


class ChatResponse(BaseModel):
    answer: str
    thread_id: str
    tools: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


class VoiceChatResponse(ChatResponse):
    voice: bool = True


class VoiceTranscribeResponse(BaseModel):
    transcript: str
    engine: str
    model: str
    duration_ms: int


class VoiceSpeakRequest(BaseModel):
    text: str = Field(min_length=1)


class ComputerUseModeRequest(BaseModel):
    thread_id: str | None = None
    source: str = "ui"
    task: str | None = None
    reason: str | None = None


class WorkspaceActionRequest(BaseModel):
    action: str = Field(min_length=1)
    url: str | None = None
    target: str | None = None
    element: str | None = None
    text: str | None = None
    command: str | None = None
    filename: str | None = None
    amount: int | None = None
    submit: bool | None = None


class ComputerUseTaskRequest(BaseModel):
    thread_id: str | None = None
    source: str = "ui"
    task: str = Field(min_length=1)


class ReindexResponse(BaseModel):
    chunks: int


class SetActiveModelRequest(BaseModel):
    model: str = Field(min_length=1)  # OpenRouter id or label (label resolved via registry.resolve)


class XOAuthStartRequest(BaseModel):
    provider: str = Field(default="xai")


class XOAuthStartResponse(BaseModel):
    provider: str
    authorize_url: str
    status: str
    message: str = ""


class XOAuthStatusResponse(BaseModel):
    xai_connected: bool
    x_api_connected: bool
    x_api_configured: bool
    private_reads_enabled: bool
    posting_enabled: bool


class CodingSessionBody(BaseModel):
    provider: ProviderName
    cwd: str = Field(min_length=1)
    access_mode: AccessMode = AccessMode.read_only
    title: str = ""


class CodingTurnBody(BaseModel):
    prompt: str = Field(min_length=1)


def _computer_use_overlay() -> DesktopActivityOverlay:
    return DesktopActivityOverlay()


def _computer_use_session(source: str = "ui") -> ComputerUseSession:
    overlay = NoopOverlay() if source == "tauri" else _computer_use_overlay()
    return ComputerUseSession(runtime=computer_use_runtime, overlay=overlay)


class ActiveModelResponse(BaseModel):
    id: str
    label: str
    provider: str
    open_weights: bool


_UI_CONVERSATIONS_PATH = REPO_ROOT / "data" / "ui" / "conversations.json"


def _read_ui_conversations() -> list[dict[str, Any]]:
    try:
        payload = json.loads(_UI_CONVERSATIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    conversations = payload.get("conversations") if isinstance(payload, dict) else payload
    return conversations if isinstance(conversations, list) else []


def _write_ui_conversations(conversations: list[dict[str, Any]]) -> None:
    _UI_CONVERSATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _UI_CONVERSATIONS_PATH.write_text(
        json.dumps({"conversations": conversations}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _conversation_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_ui_conversation(conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = dict(payload)
    record["id"] = str(record.get("id") or conversation_id)
    record["thread_id"] = str(record.get("thread_id") or record["id"])
    record["title"] = str(record.get("title") or "New chat")
    record["created"] = str(record.get("created") or "Today")
    record["pinned"] = bool(record.get("pinned", False))
    record["archived"] = bool(record.get("archived", False))
    record["projectId"] = record.get("projectId")
    record["messages"] = record.get("messages") if isinstance(record.get("messages"), list) else []
    record["updated_at"] = _conversation_timestamp()
    return record


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
    allow_origins=[
        "null",
        "http://localhost:4242",
        "http://127.0.0.1:4242",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(prefix="/api")


def _x_oauth_file(provider: str) -> Path:
    return REPO_ROOT / "data" / ("xai-oauth.json" if provider == "xai" else "x-api-oauth.json")


def _x_oauth_callback_url(provider: str) -> str:
    return f"http://127.0.0.1:8000/api/x/oauth/callback/{provider}"


def _x_oauth_status() -> XOAuthStatusResponse:
    settings = get_settings()
    return XOAuthStatusResponse(
        xai_connected=_x_oauth_file("xai").exists(),
        x_api_connected=_x_oauth_file("xapi").exists(),
        x_api_configured=bool(settings.x_api_client_id),
        private_reads_enabled=bool(settings.x_tool_allow_private_reads),
        posting_enabled=bool(settings.x_tool_allow_posts),
    )


@router.get("/x/oauth/status", response_model=XOAuthStatusResponse)
async def x_oauth_status() -> XOAuthStatusResponse:
    return _x_oauth_status()


@router.post("/x/oauth/start", response_model=XOAuthStartResponse)
async def x_oauth_start(request: XOAuthStartRequest) -> XOAuthStartResponse:
    provider = request.provider.strip().lower().replace("-", "_")
    if provider in {"x", "x_api", "xapi"}:
        provider = "xapi"
    if provider not in {"xai", "xapi"}:
        raise HTTPException(status_code=400, detail="provider must be xai or xapi")

    if provider == "xai":
        mod = _load_script_module("setup_xai_oauth")
        discovery = await asyncio.to_thread(mod.discover_oauth, 60)
        verifier, challenge = mod.make_pkce_pair()
        state = mod.secrets.token_urlsafe(32)
        nonce = mod.secrets.token_urlsafe(32)
        redirect_uri = _x_oauth_callback_url("xai")
        authorize_url = mod.build_authorize_url(
            authorization_endpoint=discovery["authorization_endpoint"],
            redirect_uri=redirect_uri,
            state=state,
            nonce=nonce,
            code_challenge=challenge,
        )
        _oauth_flows["xai"] = {
            "state": state,
            "verifier": verifier,
            "challenge": challenge,
            "redirect_uri": redirect_uri,
            "discovery": discovery,
            "created_at": time.time(),
        }
        return XOAuthStartResponse(provider="xai", authorize_url=authorize_url, status="started")

    settings = get_settings()
    if not settings.x_api_client_id:
        raise HTTPException(status_code=409, detail="Set X_API_CLIENT_ID in .env before connecting X account actions.")
    mod = _load_script_module("setup_x_api_oauth")
    verifier, challenge = mod.make_pkce_pair()
    state = mod.secrets.token_urlsafe(32)
    redirect_uri = _x_oauth_callback_url("xapi")
    authorize_url = mod.build_authorize_url(
        client_id=settings.x_api_client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=challenge,
    )
    _oauth_flows["xapi"] = {
        "state": state,
        "verifier": verifier,
        "redirect_uri": redirect_uri,
        "client_id": settings.x_api_client_id,
        "client_secret": settings.x_api_client_secret,
        "created_at": time.time(),
    }
    return XOAuthStartResponse(provider="xapi", authorize_url=authorize_url, status="started")


@router.get("/x/oauth/callback/{provider}")
async def x_oauth_callback(provider: str, code: str = "", state: str = "", error: str = "", error_description: str = "") -> HTMLResponse:
    provider = provider.strip().lower()
    if provider not in {"xai", "xapi"}:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider.")
    if error:
        return HTMLResponse(f"<html><body><h1>X OAuth failed</h1><p>{error_description or error}</p></body></html>", status_code=400)
    flow = _oauth_flows.get(provider)
    if not flow or state != flow.get("state"):
        return HTMLResponse("<html><body><h1>X OAuth failed</h1><p>State mismatch. Start the connection again from Vellum.</p></body></html>", status_code=400)
    if not code:
        return HTMLResponse("<html><body><h1>X OAuth failed</h1><p>No authorization code was returned.</p></body></html>", status_code=400)

    try:
        if provider == "xai":
            mod = _load_script_module("setup_xai_oauth")
            tokens = await asyncio.to_thread(
                mod.exchange_authorization_code,
                token_endpoint=flow["discovery"]["token_endpoint"],
                code=code,
                redirect_uri=flow["redirect_uri"],
                code_verifier=flow["verifier"],
                code_challenge=flow["challenge"],
                timeout_secs=60,
            )
            await asyncio.to_thread(mod.save_oauth_file, _x_oauth_file("xai"), tokens=tokens, discovery=flow["discovery"])
        else:
            mod = _load_script_module("setup_x_api_oauth")
            tokens = await asyncio.to_thread(
                mod.exchange_authorization_code,
                client_id=flow["client_id"],
                client_secret=flow.get("client_secret") or "",
                code=code,
                redirect_uri=flow["redirect_uri"],
                code_verifier=flow["verifier"],
                timeout_secs=60,
            )
            await asyncio.to_thread(mod.save_oauth_file, _x_oauth_file("xapi"), client_id=flow["client_id"], tokens=tokens)
    except Exception as exc:
        return HTMLResponse(f"<html><body><h1>X OAuth failed</h1><p>{str(exc)}</p></body></html>", status_code=500)
    finally:
        _oauth_flows.pop(provider, None)

    return HTMLResponse(
        "<html><body><h1>X OAuth complete</h1><p>You can close this tab and return to Vellum.</p>"
        "<script>setTimeout(function(){ window.close(); }, 900);</script></body></html>"
    )


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


def _state_values(state: Any) -> dict[str, Any]:
    if state is None:
        return {}
    if isinstance(state, dict):
        values = state.get("values", state)
    else:
        values = getattr(state, "values", {}) or {}
    return values if isinstance(values, dict) else {}


def _message_tool_calls(message: Any) -> list[Any]:
    if isinstance(message, dict):
        tool_calls = message.get("tool_calls")
        if tool_calls is None:
            tool_calls = (message.get("additional_kwargs") or {}).get("tool_calls")
    else:
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls is None:
            tool_calls = (getattr(message, "additional_kwargs", None) or {}).get("tool_calls")
    return list(tool_calls or [])


def _tool_call_field(tool_call: Any, *names: str) -> Any:
    if isinstance(tool_call, dict):
        for name in names:
            if name in tool_call:
                return tool_call.get(name)
        function = tool_call.get("function")
        if isinstance(function, dict) and "name" in names:
            return function.get("name")
        return None
    for name in names:
        value = getattr(tool_call, name, None)
        if value is not None:
            return value
    return None


def _tool_message_id(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("tool_call_id") or "")
    return str(getattr(message, "tool_call_id", "") or "")


def _pending_tool_calls(messages: list[Any]) -> list[dict[str, str]]:
    pending: dict[str, dict[str, str]] = {}
    for message in messages:
        for tool_call in _message_tool_calls(message):
            call_id = str(_tool_call_field(tool_call, "id", "tool_call_id") or "").strip()
            if not call_id:
                continue
            name = str(_tool_call_field(tool_call, "name") or "unknown_tool").strip() or "unknown_tool"
            pending[call_id] = {"id": call_id, "name": name}

        tool_call_id = _tool_message_id(message)
        if tool_call_id:
            pending.pop(tool_call_id, None)
    return list(pending.values())


async def _repair_incomplete_tool_history(thread_id: str) -> int:
    get_state = getattr(agent, "aget_state", None)
    update_state = getattr(agent, "aupdate_state", None)
    if get_state is None or update_state is None:
        return 0

    config = _thread_config(thread_id)
    try:
        state = await get_state(config)
        messages = _state_values(state).get("messages") or []
        pending = _pending_tool_calls(list(messages))
        if not pending:
            return 0

        repairs = [
            ToolMessage(
                content=(
                    f"Tool call '{item['name']}' did not complete because the previous "
                    "agent turn was interrupted before a tool result was saved. "
                    "Continue from the user's latest request."
                ),
                tool_call_id=item["id"],
                name=item["name"],
            )
            for item in pending
        ]
        await update_state(config, {"messages": repairs})
        return len(repairs)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            "Failed to repair incomplete tool history for thread %s: %s",
            thread_id,
            exc,
        )
        return 0


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

    live_result = await asyncio.to_thread(_live_dispatcher.maybe_handle, clean_message, active_thread_id)
    delegated_tools: list[str] = []
    delegated_sources: list[Source] = []
    agent_input_message = clean_message
    if live_result is not None and live_result.handled:
        live_sources = _decorate_source_list(list(live_result.sources))
        delegated_tools = list(live_result.tools)
        delegated_sources = [Source(**source) for source in live_sources]
        agent_input_message = _delegated_agent_message(clean_message, live_result, live_sources)

    async with _agent_runtime_lock:
        try:
            await _ensure_model(model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        await _repair_incomplete_tool_history(active_thread_id)
        agent_message = _agent_message_for_runtime_mode(agent_input_message)
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": agent_message}]},
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
    tools = list(dict.fromkeys([*delegated_tools, *_tool_call_names(messages)]))
    seen_source_urls = {source.url for source in delegated_sources if source.url}
    sources = list(delegated_sources)
    for source in _sources_from_messages(messages):
        if source.url and source.url in seen_source_urls:
            continue
        if source.url:
            seen_source_urls.add(source.url)
        sources.append(source)

    if answer and "blocked for privacy" not in answer.casefold():
        asyncio.create_task(_background_learn(clean_message, answer, active_thread_id))

    return ChatResponse(answer=answer, thread_id=active_thread_id, tools=tools, sources=sources)


def _audit_memory_off(thread_id: str, source: str) -> None:
    """Metadata-only breadcrumb when the user has memory turned off. No content is written."""
    try:
        from pathlib import Path
        from datetime import datetime, timezone
        audit = Path("data/memory/audit_log.jsonl")
        audit.parent.mkdir(parents=True, exist_ok=True)
        with audit.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "thread_id": thread_id,
                "source": source,
                "event": "memory_disabled",
                "memory_enabled": False,
                "outcome": "not_stored",
            }) + "\n")
    except Exception:
        pass


async def _background_learn(query: str, answer: str, thread_id: str = "default", source: str = "agent") -> None:
    try:
        data_class, _reason = classify(query)
        if data_class == DataClass.RED:
            return
        scrubber = PrivacyScrubber()
        clean_query = scrubber.scrub(query)[0] if data_class == DataClass.YELLOW else query
        clean_answer = scrubber.scrub(answer)[0] if data_class == DataClass.YELLOW else answer
        await asyncio.to_thread(store_qa_pair, clean_query, clean_answer, source)
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
        # Hermes-style: refresh the cached user model (Honcho dialectic) on a
        # cadence so the next turn's prompt reflects a deeper understanding.
        try:
            from agent.memory.memory_context import refresh_user_model

            await asyncio.to_thread(refresh_user_model, thread_id, honcho)
        except Exception:
            pass
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


def _vector_health() -> dict[str, Any]:
    """Read the embedded Chroma vector-store status WITHOUT opening a second client.

    Reuse the singleton from agent.rag.store so /health doesn't race the client
    the agent path already holds on the same storage path."""
    settings = get_settings()
    location = str(settings.chroma_path) if settings.chroma_path is not None else "(ephemeral)"
    mode = "embedded-chroma"
    try:
        from agent.rag.store import get_vector_store

        store = get_vector_store()
        collections = store.collection_names()
        return {"ok": True, "mode": mode, "location": location, "collections": collections}
    except Exception as exc:
        return {"ok": False, "mode": mode, "location": location, "error": str(exc)}


def _embedding_health() -> dict[str, Any]:
    try:
        import sentence_transformers  # noqa: F401

        return {"ok": True, "provider": "sentence-transformers"}
    except Exception as exc:
        return {"ok": False, "provider": "sentence-transformers", "error": str(exc)}


def _coding_session_json(session: CodingSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "provider": session.provider.value,
        "provider_session_id": session.provider_session_id,
        "cwd": session.cwd,
        "access_mode": session.access_mode.value,
        "title": session.title,
        "status": session.status,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _hidden_coding_file(name: str) -> bool:
    lowered = name.casefold()
    secret_names = {
        ".aws",
        ".env",
        ".envrc",
        ".netrc",
        ".npmrc",
        ".pypirc",
        ".ssh",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
    }
    return (
        lowered in secret_names
        or lowered.startswith(".env.")
        or lowered.endswith(".pem")
        or lowered.endswith(".key")
        or lowered.endswith(".p12")
        or lowered.endswith(".pfx")
    )


def _coding_project_roots() -> list[Path]:
    roots = {REPO_ROOT.resolve(), Path.cwd().resolve()}
    try:
        settings = get_settings()
        roots.add(settings.obsidian_vault_path.resolve())
        roots.add(settings.filesystem_mcp_path.resolve())
    except Exception:
        pass
    try:
        for session in coding_service.list_sessions():
            roots.add(Path(session.cwd).expanduser().resolve())
    except Exception:
        pass
    return sorted(roots, key=lambda path: str(path).casefold())


def _is_allowed_coding_project_root(path: Path) -> bool:
    return any(path == root or path.is_relative_to(root) for root in _coding_project_roots())


def _project_tree(root: str) -> dict[str, Any]:
    base = Path(root).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        raise HTTPException(status_code=404, detail="Project not found.")
    if not _is_allowed_coding_project_root(base):
        raise HTTPException(status_code=403, detail="Project root is not allowed.")
    items: list[dict[str, Any]] = []
    try:
        paths = sorted(base.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Project root is not readable.") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Project root could not be read.") from exc
    for path in paths:
        if _hidden_coding_file(path.name):
            continue
        items.append(
            {
                "name": path.name,
                "path": path.relative_to(base).as_posix(),
                "kind": "directory" if path.is_dir() else "file",
            }
        )
        if len(items) >= 250:
            break
    return {"root": str(base), "items": items}


def _coding_http_exception(exc: CodingServiceError) -> HTTPException:
    message = str(exc)
    cause = exc.__cause__
    cause_message = str(cause) if cause is not None else ""
    searchable = f"{message} {cause_message}".casefold()
    if "not found" in searchable:
        return HTTPException(status_code=404, detail=message)
    if "already has a running turn" in searchable:
        return HTTPException(status_code=409, detail=message)
    if (
        "not installed" in searchable
        or "not configured" in searchable
        or "sdk unavailable" in searchable
        or "failed to start" in searchable
    ):
        return HTTPException(status_code=503, detail=message)
    return HTTPException(status_code=400, detail=message)


def _ensure_coding_provider_ready(provider: ProviderName) -> None:
    for health in coding_service.health():
        if health.provider == provider:
            if not health.available or not health.configured:
                raise CodingServiceError(health.message)
            return
    raise CodingServiceError("Provider is not configured.")


@router.get("/health")
async def health(deep: bool = Query(default=False)) -> dict[str, Any]:
    settings = get_settings()
    body: dict[str, Any] = {
        "ok": True,
        "service": "personal-agent-api",
        "vault": {"path": str(settings.obsidian_vault_path), "exists": settings.obsidian_vault_path.exists()},
        "models": {
            "primary": settings.primary_model,
            "fallback": settings.fallback_model,
            "fast": settings.fast_model,
        },
        "mcp": {
            "apify_url": settings.apify_mcp_url,
            "filesystem_path": str(settings.filesystem_mcp_path),
        },
        "checks": {"mode": "deep" if deep else "lightweight"},
    }
    if deep:
        body["vector"] = _vector_health()
        body["embeddings"] = _embedding_health()
    return body


@router.get("/status")
async def status(deep: bool = Query(default=False)) -> dict[str, Any]:
    return await health(deep=deep)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await _run_agent(request.message, request.thread_id, request.model)


@router.get("/conversations")
async def list_conversations() -> dict[str, Any]:
    conversations = sorted(
        _read_ui_conversations(),
        key=lambda item: str(item.get("updated_at") or ""),
        reverse=True,
    )
    return {"conversations": conversations}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict[str, Any]:
    for conversation in _read_ui_conversations():
        if str(conversation.get("id")) == conversation_id:
            return {"conversation": conversation}
    raise HTTPException(status_code=404, detail="Conversation not found.")


@router.put("/conversations/{conversation_id}")
async def put_conversation(conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = _normalize_ui_conversation(conversation_id, payload)
    conversations = [item for item in _read_ui_conversations() if str(item.get("id")) != conversation_id]
    conversations.insert(0, record)
    _write_ui_conversations(conversations)
    return {"conversation": record}


@router.patch("/conversations/{conversation_id}")
async def patch_conversation(conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    conversations = _read_ui_conversations()
    for index, conversation in enumerate(conversations):
        if str(conversation.get("id")) == conversation_id:
            updated = _normalize_ui_conversation(conversation_id, {**conversation, **payload})
            conversations[index] = updated
            _write_ui_conversations(conversations)
            return {"conversation": updated}
    raise HTTPException(status_code=404, detail="Conversation not found.")


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict[str, bool]:
    conversations = [item for item in _read_ui_conversations() if str(item.get("id")) != conversation_id]
    _write_ui_conversations(conversations)
    return {"ok": True}


@router.get("/skills")
async def list_skills_catalog() -> dict[str, Any]:
    return {
        "mock": True,
        "skills": {
            "proposed": [
                {
                    "id": "sports-snapshot-brief",
                    "name": "Sports snapshot brief",
                    "trigger": "score · fixture · standings",
                    "note": "Template until user-approved skill persistence is connected.",
                },
                {
                    "id": "source-backed-answer",
                    "name": "Source-backed answer",
                    "trigger": "latest · verify · cite",
                    "note": "Uses live search and source drawer behavior.",
                },
            ],
            "active": [
                {
                    "id": "subagent-routing",
                    "name": "Sub-agent routing",
                    "trigger": "sports · x · youtube · memory",
                    "uses": 0,
                    "last": "live",
                }
            ],
            "retired": [],
        },
    }


@router.get("/automations")
async def list_automation_templates() -> dict[str, Any]:
    return {
        "mock": True,
        "automations": [
            {
                "id": "nightly-digest",
                "name": "Nightly digest",
                "schedule": "Daily at 02:00",
                "status": "template",
                "description": "Summarize new memories, sports changes, and notable watched sources.",
            },
            {
                "id": "sports-matchday-brief",
                "name": "Sports matchday brief",
                "schedule": "On demand",
                "status": "template",
                "description": "Prepare scores, fixtures, injuries, and source-backed context when asked.",
            },
            {
                "id": "memory-card-rollup",
                "name": "Memory card rollup",
                "schedule": "Before deletion windows",
                "status": "template",
                "description": "Condense aging memories into durable memory cards.",
            },
        ],
    }


@router.get("/subagents")
async def list_subagents() -> dict[str, Any]:
    from agent.master.registry import PupilRegistry

    registry = PupilRegistry.default(get_settings().obsidian_vault_path)
    descriptions = {
        "SportsAgent": "Scores, schedules, standings, injuries, and sports analysis.",
        "XAgent": "X search, account reads, bookmarks, and confirmed posting workflows.",
        "YoutubeAgent": "YouTube search, video metadata, transcripts, and summaries.",
        "MemoryAgent": "Long-term memory lookup, context packs, and preference recall.",
    }
    return {
        "subagents": [
            {
                "id": name.replace("Agent", "").casefold() or name.casefold(),
                "name": name,
                "enabled": True,
                "status": "available",
                "description": descriptions.get(name, "Specialized Vellum sub-agent."),
            }
            for name in registry.names()
        ]
    }


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


def _sse(event: str, payload: dict[str, Any] | str) -> str:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return f"event: {event}\ndata: {data}\n\n"


def _stream_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _stream_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _response_event(
    event_type: str,
    *,
    response_id: str,
    thread_id: str,
    **payload: Any,
) -> str:
    body = {
        "type": event_type,
        "response_id": response_id,
        "thread_id": thread_id,
        "created_at": _stream_now(),
        **payload,
    }
    return _sse(event_type, body)


def _response_created(*, response_id: str, thread_id: str) -> str:
    return _response_event(
        "response.created",
        response_id=response_id,
        thread_id=thread_id,
        response={"id": response_id, "status": "in_progress", "output": []},
    )


def _response_in_progress(*, response_id: str, thread_id: str) -> str:
    return _response_event(
        "response.in_progress",
        response_id=response_id,
        thread_id=thread_id,
        response={"id": response_id, "status": "in_progress"},
    )


def _response_output_item_added(
    *,
    response_id: str,
    thread_id: str,
    item: dict[str, Any],
    output_index: int = 0,
) -> str:
    return _response_event(
        "response.output_item.added",
        response_id=response_id,
        thread_id=thread_id,
        output_index=output_index,
        item=item,
    )


def _response_output_text_delta(
    *,
    response_id: str,
    thread_id: str,
    item_id: str,
    delta: str,
    output_index: int = 0,
    content_index: int = 0,
) -> str:
    return _response_event(
        "response.output_text.delta",
        response_id=response_id,
        thread_id=thread_id,
        item_id=item_id,
        output_index=output_index,
        content_index=content_index,
        delta=delta,
    )


def _response_output_item_done(
    *,
    response_id: str,
    thread_id: str,
    item: dict[str, Any],
    output_index: int = 0,
    status: str = "completed",
) -> str:
    return _response_event(
        "response.output_item.done",
        response_id=response_id,
        thread_id=thread_id,
        output_index=output_index,
        item={**item, "status": status},
    )


def _response_completed(
    *,
    response_id: str,
    thread_id: str,
    answer: str,
    tools: list[str],
    sources: list[dict[str, Any]],
) -> str:
    return _response_event(
        "response.completed",
        response_id=response_id,
        thread_id=thread_id,
        response={
            "id": response_id,
            "status": "completed",
            "thread_id": thread_id,
            "output_text": answer,
            "tools": tools,
            "sources": sources,
        },
    )


def _response_error(*, response_id: str, thread_id: str, message: str) -> str:
    return _response_event(
        "error",
        response_id=response_id,
        thread_id=thread_id,
        error={"message": message},
    )


from agent.tools.web import extract_web_sources

_ACTIVITY_LABELS = {
    "web_search": "Searched the web",
    "search_my_notes": "Searched your library",
    "read_file": "Read a note",
    "list_files": "Browsed your vault",
    "create_note": "Wrote a note",
    "append_to_note": "Updated a note",
    "context_mode": "Fetched a page",
    "x_action": "Searched X",
    "search_amazon": "Checked Amazon",
    "computer_use": "Used the desktop",
}


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _source_domain(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _source_type(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return "web"
    return "memory"


def _favicon_url(domain: str) -> str:
    if not domain:
        return ""
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"


def _decorate_source_record(record: dict[str, Any], *, source_index: int) -> dict[str, Any]:
    url = str(record.get("url") or "")
    domain = str(record.get("domain") or _source_domain(url))
    source_type = str(record.get("source_type") or _source_type(url))
    return {
        **record,
        "domain": domain,
        "source_index": int(record.get("source_index") or source_index),
        "source_type": source_type,
        "favicon_url": str(record.get("favicon_url") or (_favicon_url(domain) if source_type == "web" else "")),
        "provider_label": str(record.get("provider_label") or domain or source_type),
    }


def _decorate_source_list(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_decorate_source_record(record, source_index=index) for index, record in enumerate(records, start=1)]


def _activity_for(name: str, tool_input: Any) -> tuple[str, str]:
    label = _ACTIVITY_LABELS.get(name, f"Used {name}")
    detail = ""
    if isinstance(tool_input, dict):
        for key in ("query", "q", "path", "url", "league", "action", "text"):
            value = tool_input.get(key)
            if value:
                detail = str(value)
                break
    elif isinstance(tool_input, str):
        detail = tool_input
    return label, detail[:200]


def _tool_output_text(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    content = getattr(output, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(part.get("text") if isinstance(part, dict) else part) for part in content
        )
    return str(output)


def _sources_from_messages(messages: list) -> list[Source]:
    seen: set[str] = set()
    collected: list[Source] = []
    for message in messages:
        if getattr(message, "name", "") != "web_search":
            continue
        for record in extract_web_sources(_tool_output_text(message)):
            if record["url"] in seen:
                continue
            seen.add(record["url"])
            decorated = _decorate_source_record(
                {**record, "fetched_at": _now_iso()},
                source_index=len(collected) + 1,
            )
            collected.append(Source(**decorated))
    return collected


def _agent_message_for_runtime_mode(clean_message: str) -> str:
    status = computer_use_runtime.status()
    if not status.get("enabled") or status.get("paused"):
        return clean_message
    return (
        "Computer use mode is enabled. Treat the user's message as a live "
        "computer/browser automation instruction. Use computer_use or browser "
        "tools when action is needed, narrate concise progress, and ask for a "
        "missing runtime permission instead of pretending the action happened.\n\n"
        f"User instruction: {clean_message}"
    )


def _delegated_agent_message(clean_message: str, live_result: LiveAgentResult, live_sources: list[dict[str, Any]]) -> str:
    source_lines = []
    for index, source in enumerate(live_sources, start=1):
        title = str(source.get("title") or source.get("domain") or source.get("url") or "source")
        url = str(source.get("url") or "")
        snippet = str(source.get("snippet") or "").strip()
        line = f"[{index}] {title}: {url}" if url else f"[{index}] {title}"
        if snippet:
            line += f" - {snippet[:220]}"
        source_lines.append(line)
    sources_text = "\n".join(source_lines) if source_lines else "No external sources returned."
    return (
        "You are Vellum, the main agent. A specialist sub-agent was used as a tool. "
        "Do not expose raw tool dumps. Answer the user naturally and directly, like ChatGPT, "
        "using the specialist result as evidence. Treat the specialist result and source snippets "
        "as authoritative for current/live facts. If they conflict with your prior knowledge, "
        "follow the specialist evidence and say so briefly. Mention uncertainty when the specialist "
        "could not fully answer. Preserve exact names, dates, scores, standings, and event order from "
        "the specialist result. Do not replace a live snapshot with older model-memory facts. If the "
        "specialist result includes multiple sources, synthesize across them instead of relying on one. "
        "Keep citations/source references consistent with provided sources.\n\n"
        f"User message:\n{clean_message}\n\n"
        f"Specialist tool: {live_result.agent_name}\n"
        f"Specialist status: {live_result.status}\n"
        f"Specialist raw result:\n{live_result.answer}\n\n"
        f"Sources:\n{sources_text}"
    )


async def _next_agent_stream_event(stream_iterator, timeout_seconds: float) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(anext(stream_iterator), timeout=timeout_seconds)
    except StopAsyncIteration:
        raise
    except TimeoutError as exc:
        close = getattr(stream_iterator, "aclose", None)
        if close is not None:
            await close()
        raise TimeoutError(f"Model stream timed out after {timeout_seconds:g} seconds.") from exc


async def _stream_agent_turn(
    *,
    clean_message: str,
    active_thread_id: str,
    model: str | None,
    source: str = "agent",
    voice: bool = False,
    synthesize_audio: bool = False,
    store: bool = True,
):
    response_id = _stream_id("resp")
    message_item_id = _stream_id("msg")
    live_result = await asyncio.to_thread(_live_dispatcher.maybe_handle, clean_message, active_thread_id)
    live_sources: list[dict[str, Any]] = []
    delegated_tools: list[str] = []
    subagent_item: dict[str, Any] | None = None
    agent_input_message = clean_message
    yield _response_created(response_id=response_id, thread_id=active_thread_id)
    yield _response_in_progress(response_id=response_id, thread_id=active_thread_id)
    yield _sse("meta", {"thread_id": active_thread_id})
    if live_result is not None and live_result.handled:
        live_sources = _decorate_source_list(list(live_result.sources))
        delegated_tools = list(live_result.tools)
        agent_input_message = _delegated_agent_message(clean_message, live_result, live_sources)
        subagent_item = {
            "id": _stream_id("item"),
            "type": "subagent_call",
            "name": live_result.agent_name,
            "status": "in_progress",
            "label": f"Routed to {live_result.agent_name}",
            "detail": clean_message[:200],
        }
        yield _response_output_item_added(
            response_id=response_id,
            thread_id=active_thread_id,
            item=subagent_item,
        )
        yield _sse("activity", {"label": f"Routed to {live_result.agent_name}", "detail": clean_message[:200]})
        for tool_name in live_result.tools:
            tool_item = {
                "id": _stream_id("item"),
                "type": "tool_call",
                "name": tool_name,
                "status": "in_progress",
                "label": f"Used {tool_name}",
                "detail": "",
            }
            yield _response_output_item_added(response_id=response_id, thread_id=active_thread_id, item=tool_item)
            yield _response_output_item_done(response_id=response_id, thread_id=active_thread_id, item=tool_item)
            yield _sse("tool", {"name": tool_name})
        for source_record in live_sources:
            source_item = {
                "id": _stream_id("item"),
                "type": "source",
                "status": "completed",
                "source": source_record,
            }
            yield _response_output_item_added(response_id=response_id, thread_id=active_thread_id, item=source_item)
            yield _response_output_item_done(response_id=response_id, thread_id=active_thread_id, item=source_item)
            yield _sse("source", source_record)
        subagent_status = "failed" if live_result.status == "error" else "completed"
        yield _response_output_item_done(
            response_id=response_id,
            thread_id=active_thread_id,
            item=subagent_item,
            status=subagent_status,
        )

    async with _agent_runtime_lock:
        answer_parts: list[str] = []
        tool_names: list[str] = list(delegated_tools)
        sources: list[dict] = list(live_sources)
        seen_urls: set[str] = {str(source.get("url") or "") for source in live_sources if source.get("url")}
        active_tool_items: dict[str, dict[str, Any]] = {}
        message_item = {
            "id": message_item_id,
            "type": "message",
            "role": "assistant",
            "status": "in_progress",
        }
        message_item_started = False
        try:
            await _ensure_model(model)
            await _repair_incomplete_tool_history(active_thread_id)
            if computer_use_runtime.status().get("enabled") and not computer_use_runtime.status().get("paused"):
                try:
                    _computer_use_session(source).submit_task(clean_message, source=source, thread_id=active_thread_id)
                except ComputerUseSessionError as exc:
                    computer_use_runtime.record_event(
                        "task_rejected",
                        str(exc),
                        tool="computer_use_session",
                        data={"thread_id": active_thread_id, "source": source},
                    )
            agent_message = _agent_message_for_runtime_mode(agent_input_message)
            stream = agent.astream_events(
                {"messages": [{"role": "user", "content": agent_message}]},
                config=_thread_config(active_thread_id),
                version="v2",
            )
            stream_iterator = stream.__aiter__()
            timeout_seconds = float(get_settings().llm_stream_timeout_seconds)
            while True:
                try:
                    event = await _next_agent_stream_event(stream_iterator, timeout_seconds)
                except StopAsyncIteration:
                    break
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    text = _chunk_text(event.get("data", {}).get("chunk"))
                    if text:
                        answer_parts.append(text)
                        if not message_item_started:
                            yield _response_output_item_added(
                                response_id=response_id,
                                thread_id=active_thread_id,
                                item=message_item,
                            )
                            message_item_started = True
                        yield _response_output_text_delta(
                            response_id=response_id,
                            thread_id=active_thread_id,
                            item_id=message_item_id,
                            delta=text,
                        )
                        yield _sse("token", {"text": text})
                elif kind == "on_tool_start":
                    name = event.get("name") or ""
                    if name:
                        if str(name) not in tool_names:
                            tool_names.append(str(name))
                        label, detail = _activity_for(str(name), event.get("data", {}).get("input"))
                        item = {
                            "id": _stream_id("item"),
                            "type": "tool_call",
                            "name": str(name),
                            "status": "in_progress",
                            "label": label,
                            "detail": detail,
                        }
                        active_tool_items[str(name)] = item
                        yield _response_output_item_added(
                            response_id=response_id,
                            thread_id=active_thread_id,
                            item=item,
                        )
                        yield _sse("tool", {"name": name})
                        yield _sse("activity", {"label": label, "detail": detail})
                elif kind == "on_tool_end":
                    if (event.get("name") or "") == "web_search":
                        output_text = _tool_output_text(event.get("data", {}).get("output"))
                        for record in extract_web_sources(output_text):
                            if record["url"] in seen_urls:
                                continue
                            seen_urls.add(record["url"])
                            record = _decorate_source_record(
                                {**record, "fetched_at": _now_iso()},
                                source_index=len(sources) + 1,
                            )
                            sources.append(record)
                            source_item = {
                                "id": _stream_id("item"),
                                "type": "source",
                                "status": "completed",
                                "source": record,
                            }
                            yield _response_output_item_added(response_id=response_id, thread_id=active_thread_id, item=source_item)
                            yield _response_output_item_done(response_id=response_id, thread_id=active_thread_id, item=source_item)
                            yield _sse("source", record)
                    done_item = active_tool_items.pop(str(event.get("name") or ""), None)
                    if done_item:
                        yield _response_output_item_done(
                            response_id=response_id,
                            thread_id=active_thread_id,
                            item=done_item,
                        )
                capture_from_stream_event(
                    ledger=_api_ledger,
                    event=event,
                    thread_id=active_thread_id,
                    fallback_model=get_settings().primary_model,
                    source="api",
                )
            answer = "".join(answer_parts).strip() or "No response."
            source_models = [Source(**record) for record in sources]
            if voice:
                response: ChatResponse = VoiceChatResponse(answer=answer, thread_id=active_thread_id, tools=tool_names, sources=source_models)
            else:
                response = ChatResponse(answer=answer, thread_id=active_thread_id, tools=tool_names, sources=source_models)
            if answer and "blocked for privacy" not in answer.casefold():
                (asyncio.create_task(_background_learn(clean_message, answer, active_thread_id, source=source)) if store else _audit_memory_off(active_thread_id, source))
            yield _sse("final", response.model_dump_json())
            if message_item_started:
                yield _response_output_item_done(
                    response_id=response_id,
                    thread_id=active_thread_id,
                    item=message_item,
                )
            yield _response_completed(
                response_id=response_id,
                thread_id=active_thread_id,
                answer=answer,
                tools=tool_names,
                sources=sources,
            )
            if synthesize_audio and answer != "No response.":
                async for audio_event in _synthesize_audio_event(answer):
                    yield audio_event
        except asyncio.CancelledError:
            await asyncio.shield(_repair_incomplete_tool_history(active_thread_id))
            raise
        except Exception as exc:
            await _repair_incomplete_tool_history(active_thread_id)
            yield _response_error(response_id=response_id, thread_id=active_thread_id, message=str(exc))
            yield _sse("error", {"error": str(exc)})


async def _synthesize_audio_event(text: str):
    try:
        wav = await asyncio.to_thread(get_tts_engine().synthesize_wav, text)
    except Exception:
        return
    if wav:
        yield _sse("audio", {"text": text, "wav_b64": base64.b64encode(wav).decode("ascii")})


def _computer_use_mode_intent(text: str) -> str | None:
    normalized = "".join(char if char.isalnum() else " " for char in text.casefold())
    normalized = " ".join(normalized.split())
    intents = {
        "enable": {
            "enable computer use",
            "enable computer use mode",
            "turn on computer use",
            "turn computer use on",
            "computer use on",
            "start computer use",
            "start computer use mode",
        },
        "disable": {
            "disable computer use",
            "disable computer use mode",
            "turn off computer use",
            "turn computer use off",
            "computer use off",
            "stop computer use",
            "stop computer use mode",
        },
        "pause": {
            "pause computer use",
            "pause computer use mode",
        },
        "resume": {
            "resume computer use",
            "resume computer use mode",
        },
    }
    for intent, phrases in intents.items():
        if normalized in phrases:
            return intent
    return None


def _apply_computer_use_intent(
    intent: str,
    *,
    source: str,
    thread_id: str,
    task: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if intent == "enable":
        status = _computer_use_session(source).start(source=source, thread_id=thread_id, task=task)
        return "Computer use is on. I have control when you give me a task.", status
    if intent == "disable":
        status = _computer_use_session(source).stop(source=source)
        return "Computer use is off. I am back in default mode.", status
    if intent == "pause":
        status = _computer_use_session(source).pause(source=source)
        return "Computer use is paused.", status
    if intent == "resume":
        status = _computer_use_session(source).resume(source=source)
        return "Computer use is ready again.", status
    return "I could not change computer use mode.", computer_use_runtime.status()


async def _stream_computer_use_command(
    *,
    clean_message: str,
    intent: str,
    active_thread_id: str,
    source: str,
    voice: bool = False,
    synthesize_audio: bool = False,
):
    answer, status = _apply_computer_use_intent(
        intent,
        source=source,
        thread_id=active_thread_id,
        task=None,
    )
    response: ChatResponse
    if voice:
        response = VoiceChatResponse(answer=answer, thread_id=active_thread_id, tools=[])
    else:
        response = ChatResponse(answer=answer, thread_id=active_thread_id, tools=[])
    yield _sse("meta", {"thread_id": active_thread_id})
    yield _sse("computer_use", {"intent": intent, "status": status})
    yield _sse("token", {"text": answer})
    yield _sse("final", response.model_dump_json())
    if synthesize_audio:
        async for audio_event in _synthesize_audio_event(answer):
            yield audio_event
    try:
        await _background_learn(clean_message, answer, active_thread_id, source="computer_use")
    except Exception:
        pass


@router.get("/computer-use/status")
async def computer_use_status() -> dict[str, Any]:
    return computer_use_runtime.status()


def _workspace_action_payload(request: WorkspaceActionRequest) -> dict[str, Any]:
    return {key: value for key, value in request.model_dump().items() if value is not None}


@router.post("/computer-use/workspace/action")
async def computer_use_workspace_action(request: WorkspaceActionRequest) -> dict[str, Any]:
    params = _workspace_action_payload(request)
    try:
        result = await asyncio.to_thread(workspace_worker.run, params)
    except WorkspaceActionError as exc:
        computer_use_runtime.record_event(
            "workspace_error",
            str(exc),
            tool="computer_use_workspace",
            data={"action": request.action},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    computer_use_runtime.record_event(
        "workspace_action",
        result.message,
        tool="computer_use_workspace",
        data={
            "action": result.action,
            "status": result.status,
            "result": result.data,
        },
    )
    return {
        "action": result.action,
        "status": result.status,
        "message": result.message,
        "data": result.data,
    }


@router.post("/computer-use/session/start")
async def computer_use_session_start(request: ComputerUseModeRequest) -> dict[str, Any]:
    active_thread_id = request.thread_id or get_settings().thread_id
    try:
        status = _computer_use_session(request.source).start(
            source=request.source, thread_id=active_thread_id, task=request.task
        )
    except ComputerUseSessionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": status, "message": "Computer use is on. I have control when you give me a task."}


@router.post("/computer-use/session/stop")
async def computer_use_session_stop(request: ComputerUseModeRequest) -> dict[str, Any]:
    status = _computer_use_session(request.source).stop(source=request.source, reason=request.reason)
    return {"status": status, "message": "Computer use is off. I am back in default mode."}


@router.post("/computer-use/session/pause")
async def computer_use_session_pause(request: ComputerUseModeRequest) -> dict[str, Any]:
    status = _computer_use_session(request.source).pause(source=request.source)
    return {"status": status, "message": "Computer use is paused."}


@router.post("/computer-use/session/resume")
async def computer_use_session_resume(request: ComputerUseModeRequest) -> dict[str, Any]:
    status = _computer_use_session(request.source).resume(source=request.source)
    return {"status": status, "message": "Computer use is ready again."}


@router.post("/computer-use/session/task")
async def computer_use_session_task(request: ComputerUseTaskRequest) -> dict[str, Any]:
    active_thread_id = request.thread_id or get_settings().thread_id
    try:
        result = _computer_use_session(request.source).submit_task(
            request.task, source=request.source, thread_id=active_thread_id
        )
    except ComputerUseSessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": computer_use_runtime.status(), "result": result}


@router.get("/computer-use/session/status")
async def computer_use_session_status() -> dict[str, Any]:
    return _computer_use_session().status()


@router.post("/computer-use/enable")
async def computer_use_enable(request: ComputerUseModeRequest) -> dict[str, Any]:
    return await computer_use_session_start(request)


@router.post("/computer-use/disable")
async def computer_use_disable(request: ComputerUseModeRequest) -> dict[str, Any]:
    return await computer_use_session_stop(request)


@router.post("/computer-use/pause")
async def computer_use_pause(request: ComputerUseModeRequest) -> dict[str, Any]:
    return await computer_use_session_pause(request)


@router.post("/computer-use/resume")
async def computer_use_resume(request: ComputerUseModeRequest) -> dict[str, Any]:
    return await computer_use_session_resume(request)


@router.get("/computer-use/events")
async def computer_use_events() -> StreamingResponse:
    async def events():
        yield _sse(
            "computer_use",
            {"status": computer_use_runtime.status(), "recent": computer_use_runtime.recent_events()[-20:]},
        )
        async for event in computer_use_runtime.subscribe():
            yield _sse("computer_use", {"event": event, "status": computer_use_runtime.status()})

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    clean_message = request.message.strip()
    if not clean_message:
        raise HTTPException(status_code=400, detail="message cannot be empty")
    active_thread_id = request.thread_id or get_settings().thread_id
    computer_use_intent = _computer_use_mode_intent(clean_message)
    if computer_use_intent:
        return StreamingResponse(
            _stream_computer_use_command(
                clean_message=clean_message,
                intent=computer_use_intent,
                active_thread_id=active_thread_id,
                source="voice" if request.voice else "text",
                voice=request.voice,
            ),
            media_type="text/event-stream",
        )

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

    return StreamingResponse(
        _stream_agent_turn(
            clean_message=clean_message,
            active_thread_id=active_thread_id,
            model=request.model,
            source="voice" if request.voice else "agent",
            voice=request.voice,
            store=request.store,
        ),
        media_type="text/event-stream",
    )


async def _read_voice_transcript(audio: UploadFile) -> VoiceTranscribeResponse:
    started = time.perf_counter()
    audio_bytes = await audio.read()
    try:
        stt = get_stt_engine()
        transcript = await asyncio.to_thread(stt.transcribe_wav, audio_bytes)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    transcript = " ".join((transcript or "").split())
    if not transcript:
        raise HTTPException(status_code=400, detail="No speech detected.")
    return VoiceTranscribeResponse(
        transcript=transcript,
        engine=getattr(stt, "engine", "unknown"),
        model=getattr(stt, "model", "unknown"),
        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
    )


@router.post("/voice/transcribe", response_model=VoiceTranscribeResponse)
async def voice_transcribe(audio: UploadFile = File(...)) -> VoiceTranscribeResponse:
    return await _read_voice_transcript(audio)


@router.post("/voice/turn")
async def voice_turn(
    audio: UploadFile = File(...),
    thread_id: str | None = Form(default=None),
    model: str | None = Form(default=None),
) -> StreamingResponse:
    result = await _read_voice_transcript(audio)
    active_thread_id = thread_id or get_settings().thread_id
    computer_use_intent = _computer_use_mode_intent(result.transcript)

    async def events():
        yield _sse("transcript", {"text": result.transcript, "engine": result.engine, "model": result.model})
        if computer_use_intent:
            async for item in _stream_computer_use_command(
                clean_message=result.transcript,
                intent=computer_use_intent,
                active_thread_id=active_thread_id,
                source="voice",
                voice=True,
                synthesize_audio=True,
            ):
                yield item
            return
        async for item in _stream_agent_turn(
            clean_message=result.transcript,
            active_thread_id=active_thread_id,
            model=model or None,
            source="voice",
            voice=True,
            synthesize_audio=True,
        ):
            yield item

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/voice/speak")
async def voice_speak(request: VoiceSpeakRequest) -> Response:
    try:
        wav = await asyncio.to_thread(get_tts_engine().synthesize_wav, request.text)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=wav, media_type="audio/wav")


@router.post("/vault/reindex", response_model=ReindexResponse)
async def reindex() -> ReindexResponse:
    if not get_settings().enable_vector_search:
        raise HTTPException(status_code=409, detail="vector search is disabled")
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


def _probe_mcp_server(entry: dict[str, Any]) -> dict[str, Any]:
    if not entry.get("configured"):
        return {"reachable": False, "status": "not_configured"}

    name = str(entry.get("name") or "")
    endpoint = str(entry.get("endpoint") or "")
    if name == "filesystem":
        path = Path(endpoint)
        return {
            "reachable": path.exists() and path.is_dir(),
            "status": "directory_ok" if path.exists() and path.is_dir() else "directory_missing",
        }

    if name in {"playwright", "context_mode"}:
        command = endpoint.split(" ", 1)[0]
        available = bool(shutil.which(command))
        return {
            "reachable": available,
            "status": "command_available" if available else "command_missing",
        }

    if endpoint.startswith(("http://", "https://")):
        try:
            req = urllib.request.Request(endpoint, method="HEAD")
            with urllib.request.urlopen(req, timeout=2) as response:
                return {"reachable": True, "status": f"http_{response.status}"}
        except urllib.error.HTTPError as exc:
            return {"reachable": exc.code < 500, "status": f"http_{exc.code}"}
        except Exception as exc:
            return {"reachable": False, "status": f"unreachable:{type(exc).__name__}"}

    return {"reachable": False, "status": "unsupported_endpoint"}


@router.get("/mcp/health")
async def mcp_health(probe: bool = Query(default=False)) -> dict[str, Any]:
    """Per-MCP-server configuration + reachability hint.

    Reports whether each server has its required env vars set. With
    probe=true, performs side-effect-free filesystem, command, and HTTP
    reachability checks. It does not invoke MCP tools."""
    settings = get_settings()
    servers: list[dict[str, Any]] = []

    def _entry(name: str, configured: bool, url_or_cmd: str, notes: str = "") -> dict[str, Any]:
        entry = {
            "name": name,
            "configured": configured,
            "endpoint": url_or_cmd,
            "reachable": None,
            "status": "probe_disabled",
            "probe": "disabled",
            "notes": notes,
        }
        if probe:
            entry.update(_probe_mcp_server(entry))
            entry["probe"] = "live"
        return entry

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
        notes="Amazon scraper; requires APIFY_API_TOKEN. YouTube now uses SerpAPI.",
    ))
    servers.append(_entry(
        "serpapi",
        configured=bool(settings.serpapi_api_key) and settings.serpapi_base_url.startswith("http"),
        url_or_cmd=settings.serpapi_base_url,
        notes="Sports Google results plus YouTube search/video/transcript APIs; logs redacted search metadata.",
    ))
    servers.append(_entry(
        "tavily",
        configured=bool(settings.tavily_api_key) and settings.tavily_mcp_url.startswith("http"),
        url_or_cmd=settings.tavily_mcp_url,
        notes="Shared live web research/search MCP; API key is supplied out-of-band by Vellum.",
    ))
    servers.append(_entry(
        "firecrawl",
        configured=bool(settings.firecrawl_api_key) and bool(settings.firecrawl_mcp_command),
        url_or_cmd=f"{settings.firecrawl_mcp_command} {settings.firecrawl_mcp_args}",
        notes="Shared page fetch/crawl/extract MCP; reads URLs and returns LLM-ready content.",
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
    vector = _vector_health()

    honcho_reachable = False
    try:
        req = urllib.request.Request(settings.honcho_base_url, method="HEAD")
        with urllib.request.urlopen(req, timeout=1):
            honcho_reachable = True
    except Exception:
        honcho_reachable = False

    return {
        "mcp_servers": servers,
        "vector": vector,
        "honcho": {
            "base_url": settings.honcho_base_url,
            "reachable": honcho_reachable,
            "notes": "Self-hosted via Docker; if down, identity-memory layer is dead but chat still works.",
        },
    }


@router.get("/plugins")
async def list_plugins() -> dict[str, Any]:
    health_result = mcp_health(probe=False)
    if inspect.isawaitable(health_result):
        health_result = await health_result
    servers = health_result.get("mcp_servers", []) if isinstance(health_result, dict) else []
    plugins = [
        {
            "id": str(server.get("name") or ""),
            "name": str(server.get("name") or "").replace("_", " ").title(),
            "type": "mcp",
            "configured": bool(server.get("configured")),
            "status": str(server.get("status") or "unknown"),
            "notes": str(server.get("notes") or ""),
        }
        for server in servers
        if server.get("name")
    ]
    return {"plugins": plugins}


@router.post("/settings/active-model", response_model=ActiveModelResponse)
async def set_active_model(request: SetActiveModelRequest) -> ActiveModelResponse:
    """Switch the runtime active model and invalidate the cached LangGraph agent
    so the next chat turn rebuilds with the new model."""
    from agent.llm.providers import get_provider_registry

    async with _agent_runtime_lock:
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
        "chroma_path": str(settings.chroma_path) if settings.chroma_path is not None else None,
        "enable_nightly_digest": settings.enable_nightly_digest,
        "enable_vault_watcher": settings.enable_vault_watcher,
    }


@router.get("/coding/health")
async def coding_health() -> dict[str, Any]:
    providers = []
    for health in coding_service.health():
        providers.append(
            {
                "provider": health.provider.value,
                "available": health.available,
                "configured": health.configured,
                "message": health.message,
            }
        )
    return {"providers": providers}


@router.get("/coding/sessions")
async def coding_sessions() -> dict[str, Any]:
    return {"sessions": [_coding_session_json(session) for session in coding_service.list_sessions()]}


@router.post("/coding/sessions")
async def coding_session_create(body: CodingSessionBody) -> dict[str, Any]:
    try:
        _ensure_coding_provider_ready(body.provider)
        session = await coding_service.create_session(
            CodingSessionCreate(
                provider=body.provider,
                cwd=body.cwd,
                access_mode=body.access_mode,
                title=body.title,
            )
        )
    except CodingServiceError as exc:
        raise _coding_http_exception(exc) from exc
    return _coding_session_json(session)


@router.get("/coding/sessions/{session_id}")
async def coding_session_get(session_id: str) -> dict[str, Any]:
    try:
        return _coding_session_json(coding_service.get_session(session_id))
    except CodingServiceError as exc:
        raise _coding_http_exception(exc) from exc


@router.post("/coding/sessions/{session_id}/turns/stream")
async def coding_turn_stream(session_id: str, body: CodingTurnBody) -> StreamingResponse:
    try:
        session = coding_service.get_session(session_id)
        if session.status == "running":
            raise CodingServiceError("Coding session already has a running turn.")
        _ensure_coding_provider_ready(session.provider)
        stream = coding_service.run_turn(session_id, body.prompt)
        first_event = await anext(stream)
    except CodingServiceError as exc:
        raise _coding_http_exception(exc) from exc
    except StopAsyncIteration:
        async def empty_events():
            if False:
                yield ""

        return StreamingResponse(empty_events(), media_type="text/event-stream")

    async def events():
        yield coding_sse(first_event)
        try:
            async for event in stream:
                yield coding_sse(event)
        except CodingServiceError as exc:
            yield _sse("error", {"type": "error", "message": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/coding/sessions/{session_id}/stop")
async def coding_session_stop(session_id: str) -> dict[str, Any]:
    try:
        await coding_service.stop_turn(session_id)
    except CodingServiceError as exc:
        raise _coding_http_exception(exc) from exc
    return {"ok": True}


@router.get("/coding/sessions/{session_id}/events")
async def coding_session_events(session_id: str) -> dict[str, Any]:
    try:
        return {"events": [event_payload(event) for event in coding_service.list_events(session_id)]}
    except CodingServiceError as exc:
        raise _coding_http_exception(exc) from exc


@router.get("/coding/projects/tree")
async def coding_project_tree(root: str) -> dict[str, Any]:
    return _project_tree(root)


@router.get("/coding/projects/recent")
async def coding_recent_projects() -> dict[str, Any]:
    return {"projects": []}


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
            "scope": "amazon scraper",
            "enabled": True,
        },
        {
            "id": "builtin.serpapi",
            "label": "SerpAPI",
            "category": "Built-in",
            "url": settings.serpapi_base_url,
            "scope": "sports Google search + YouTube search/video/transcripts",
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
