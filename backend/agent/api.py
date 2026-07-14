"""HTTP API layer for the personal agent."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import importlib.util
import inspect
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import time
from typing import Any, Literal
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
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
from agent.contracts.capabilities import public_capability_contract
from agent.agents.live_dispatcher import LiveAgentDispatcher
from agent.graph.agent import agent
from agent.memory.honcho_client import HonchoMemory
from agent.memory.runtime import get_memory_orchestrator
from agent.memory.project_context import ProjectContext
from agent.memory.sessions import SessionsReader
from agent.master.runtime import DelegationRuntime
from agent.profiles import ProfileRegistry
from agent.llm.routing.api import router as llm_routing_router
from agent.llm.routing.runtime import reset_routing_runtime
from agent.obsidian.ingester import VaultIngester
from agent.obsidian.conversation_export import archive_conversation_projection, export_conversations
from agent.obsidian.wiki_api import router as knowledge_router
from agent.obsidian.watcher import start_vault_watcher
from agent.plugins.agent_reach import agent_reach_plugin_status
from agent.plugins.memory_orchestrator import memory_orchestrator_plugin_status
from agent.plugins.portable import discover_portable_plugins
from agent.plugins.spotify_runtime import (
    SpotifyAuthError,
    SpotifyError,
    SpotifyRateLimited,
    portable_spotify_status,
    spotify_authorization_url,
    spotify_client as runtime_spotify_client,
    spotify_devices,
    spotify_pkce_pair,
    spotify_playback,
    spotify_store as runtime_spotify_store,
)
from agent.skills import SkillCatalog, SkillSurfaceService, SkillUsageIntelligence, create_skill_source_router
from agent.skills.manager import SkillMutationError
from agent.privacy.classifier import DataClass, classify
from agent.privacy.scrubber import PrivacyScrubber
from agent.scheduler.digest import start_scheduler
from agent.telemetry.hooks import capture_from_invoke_result, capture_from_stream_event
from agent.telemetry.usage_ledger import UsageLedger
from agent.terminal.profiles import get_profile as get_terminal_profile
from agent.terminal.profiles import list_profiles as list_terminal_profiles
from agent.terminal.session import TerminalSessionManager
from agent.tools.skill_bundles import skill_bundles
from agent.tools.skill_curator import skill_curator
from agent.tools.skill_hub import skill_hub
from agent.voice.stt import get_stt_engine
from agent.voice.tts import get_tts_engine

_api_ledger = UsageLedger(REPO_ROOT / "data" / "memory" / "usage.db")
_memory_orchestrator = get_memory_orchestrator()
_fts5_memory = _memory_orchestrator.fts5
_dreaming_status: dict[str, Any] = {"status": "idle", "last_run": None, "last_result": None}
_DREAMING_MIN_PENDING = max(1, int(os.getenv("VELLUM_DREAMING_MIN_PENDING", "3")))
_DREAMING_COOLDOWN_SECONDS = max(60, int(os.getenv("VELLUM_DREAMING_COOLDOWN_SECONDS", "900")))
_dreaming_lock = asyncio.Lock()
terminal_session_manager = TerminalSessionManager()
coding_service = CodingSessionService()
_agent_runtime_lock = asyncio.Lock()
_profile_registry = ProfileRegistry()
_delegation_runtime = DelegationRuntime(
    profile_registry=_profile_registry,
    memory_orchestrator=_memory_orchestrator,
)
_live_dispatcher = LiveAgentDispatcher(
    vault_root=get_settings().obsidian_vault_path,
    delegation_runtime=_delegation_runtime,
)
_oauth_flows: dict[str, dict[str, Any]] = {}
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8000/api/plugins/spotify/oauth/callback"

_project_context_singleton: ProjectContext | None = None
_skill_surface_singleton: SkillSurfaceService | None = None


def _project_context() -> ProjectContext:
    global _project_context_singleton
    if _project_context_singleton is None:
        s = get_settings()
        _project_context_singleton = ProjectContext(vault_root=s.obsidian_vault_path)
    return _project_context_singleton


def _skill_surface() -> SkillSurfaceService:
    global _skill_surface_singleton
    if _skill_surface_singleton is None:
        _skill_surface_singleton = SkillSurfaceService(
            REPO_ROOT / ".skills",
            logs_root=REPO_ROOT / "data" / "logs" / "curator",
            sources=create_skill_source_router(skills_root=REPO_ROOT / ".skills"),
        )
    return _skill_surface_singleton


def _spotify_store():
    return runtime_spotify_store()


def _spotify_client():
    return runtime_spotify_client()


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
    force_web_search: bool = False
    attachments: list["ChatAttachment"] = Field(default_factory=list)


class ChatAttachment(BaseModel):
    name: str = ""
    kind: str = ""
    mime_type: str = ""
    data_url: str | None = None
    url: str | None = None


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


class ProviderKeyRequest(BaseModel):
    provider: str = Field(min_length=1)
    api_key: str = Field(min_length=1)


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


class SpotifyOAuthStartRequest(BaseModel):
    client_id: str = Field(min_length=1)


class SpotifyOAuthStartResponse(BaseModel):
    authorization_url: str
    redirect_uri: str


class SpotifyStatusResponse(BaseModel):
    connected: bool
    status: str
    account_name: str = ""
    product: str = ""
    scopes: list[str] = Field(default_factory=list)
    redirect_uri: str = SPOTIFY_REDIRECT_URI


class SpotifyPlayerActionRequest(BaseModel):
    action: Literal[
        "play",
        "pause",
        "next",
        "previous",
        "seek",
        "set_volume",
        "set_shuffle",
        "set_repeat",
        "transfer",
    ]
    device_id: str | None = None
    position_ms: int | None = Field(default=None, ge=0)
    volume_percent: int | None = Field(default=None, ge=0, le=100)
    shuffle: bool | None = None
    state: Literal["track", "context", "off"] | None = None
    play: bool = False


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


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    return str(message.get("text") or message.get("content") or "").strip()


def _message_role(message: Any) -> str:
    if not isinstance(message, dict):
        return "message"
    return str(message.get("role") or "message").strip().lower()


def _conversation_turns(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    messages = conversation.get("messages") if isinstance(conversation.get("messages"), list) else []
    turns: list[dict[str, Any]] = []
    pending_user: dict[str, Any] | None = None
    for index, message in enumerate(messages):
        role = _message_role(message)
        text = _message_text(message)
        if not text:
            continue
        if role == "user":
            pending_user = {"index": index, "text": text, "id": str(message.get("id") or index) if isinstance(message, dict) else str(index)}
            continue
        if role == "assistant" and pending_user is not None:
            if text.lower() == "stopped.":
                pending_user = None
                continue
            turns.append(
                {
                    "index": pending_user["index"],
                    "user": pending_user["text"],
                    "assistant": text,
                    "message_id": pending_user["id"],
                }
            )
            pending_user = None
    return turns


def _text_terms(text: str) -> set[str]:
    stop_words = {
        "about",
        "after",
        "again",
        "answer",
        "chat",
        "conversation",
        "does",
        "earlier",
        "from",
        "have",
        "know",
        "many",
        "previous",
        "recent",
        "remember",
        "said",
        "tell",
        "that",
        "there",
        "this",
        "what",
        "when",
        "where",
        "which",
        "with",
    }
    return {term for term in re.findall(r"[A-Za-z0-9]+", text.casefold()) if len(term) > 2 and term not in stop_words}


def _conversation_relevance(conversation: dict[str, Any], query_terms: set[str]) -> int:
    if not query_terms:
        return 0
    title = str(conversation.get("title") or "")
    messages = conversation.get("messages") if isinstance(conversation.get("messages"), list) else []
    haystack = " ".join([title, *(_message_text(message) for message in messages)])
    return len(query_terms.intersection(_text_terms(haystack)))


def _thread_user_messages(thread_id: str, *, limit: int = 6) -> list[str]:
    if not thread_id:
        return []
    for conversation in _read_ui_conversations():
        cid = str(conversation.get("thread_id") or conversation.get("id") or "")
        if cid != thread_id:
            continue
        messages = conversation.get("messages") if isinstance(conversation.get("messages"), list) else []
        user_messages = [_message_text(message) for message in messages if _message_role(message) == "user" and _message_text(message)]
        return user_messages[-max(0, int(limit)) :]
    return []


def _is_short_correction(message: str) -> bool:
    clean = message.strip()
    if not clean:
        return False
    if clean.endswith("*"):
        return True
    terms = _text_terms(clean)
    return 0 < len(clean) <= 18 and 0 < len(terms) <= 3


def _has_memory_recall_language(message: str) -> bool:
    lowered = message.casefold()
    phrases = (
        "from my chat",
        "from my chats",
        "from our chat",
        "from our chats",
        "from the chat",
        "in my chat",
        "in our chat",
        "previous chat",
        "previous chats",
        "older chat",
        "old chat",
        "conversation history",
        "chat history",
        "our history",
        "we spoke",
        "we have spoken",
        "we've spoken",
        "spoken about",
        "we speak",
        "we talked",
        "we discussed",
        "did i ask",
        "have i asked",
        "what did i ask",
        "what did we",
        "pull them up",
        "find it from memory",
        "search my memory",
        "search your memory",
        "search my vault",
        "from the vault",
    )
    return any(phrase in lowered for phrase in phrases)


def _is_memory_recall_request(clean_message: str, thread_id: str) -> bool:
    if _has_memory_recall_language(clean_message):
        return True
    if not _is_short_correction(clean_message):
        return False
    recent = _thread_user_messages(thread_id, limit=4)
    previous = " ".join(recent[:-1] if recent and recent[-1].strip() == clean_message.strip() else recent)
    return _has_memory_recall_language(previous)


def _fts_recall_query(message: str) -> str:
    terms = []
    for term in re.findall(r"[A-Za-z0-9]+", message.casefold()):
        if len(term) <= 1:
            continue
        if len(term) == 2 and not any(ch.isdigit() for ch in term):
            continue
        if term in {"the", "and", "for", "from", "chat", "chats", "what", "when", "where", "did", "does", "how", "many", "about"}:
            continue
        terms.append(term)
    terms = list(dict.fromkeys(terms))[:8]
    return " OR ".join(terms) if terms else message.strip()


def _import_ui_conversations_to_memory(limit: int | None = None) -> dict[str, int]:
    conversations = _read_ui_conversations()
    fts5 = getattr(_memory_orchestrator, "fts5", _fts5_memory)
    indexed_turns = 0
    skipped_turns = 0
    scanned_turns = 0
    max_turns = max(0, int(limit)) if limit is not None else None
    for conversation in conversations:
        cid = str(conversation.get("thread_id") or conversation.get("id") or "ui-chat")
        title = str(conversation.get("title") or "Untitled chat")
        for turn in _conversation_turns(conversation):
            if max_turns is not None and scanned_turns >= max_turns:
                return {"indexed_turns": indexed_turns, "skipped_turns": skipped_turns, "scanned_turns": scanned_turns}
            scanned_turns += 1
            source_id = f"ui-conversation:{cid}:{turn['message_id']}"
            if hasattr(fts5, "source_path_exists") and fts5.source_path_exists(source_id):
                skipped_turns += 1
                continue
            content = (
                f"Conversation: {title}\n"
                f"Thread: {cid}\n"
                f"Q: {turn['user']}\n"
                f"A: {turn['assistant']}"
            )
            fts5.add_document(content=content, thread_id=cid, source_paths=[source_id, f"ui-conversation:{cid}"])
            indexed_turns += 1
    return {"indexed_turns": indexed_turns, "skipped_turns": skipped_turns, "scanned_turns": scanned_turns}


def _index_ui_conversation(conversation: dict[str, Any]) -> dict[str, int]:
    fts5 = getattr(_memory_orchestrator, "fts5", _fts5_memory)
    cid = str(conversation.get("thread_id") or conversation.get("id") or "ui-chat")
    title = str(conversation.get("title") or "Untitled chat")
    indexed_turns = 0
    skipped_turns = 0
    for turn in _conversation_turns(conversation):
        source_id = f"ui-conversation:{cid}:{turn['message_id']}"
        if hasattr(fts5, "source_path_exists") and fts5.source_path_exists(source_id):
            skipped_turns += 1
            continue
        content = (
            f"Conversation: {title}\n"
            f"Thread: {cid}\n"
            f"Q: {turn['user']}\n"
            f"A: {turn['assistant']}"
        )
        fts5.add_document(content=content, thread_id=cid, source_paths=[source_id, f"ui-conversation:{cid}"])
        indexed_turns += 1
    return {
        "indexed_turns": indexed_turns,
        "skipped_turns": skipped_turns,
        "scanned_turns": indexed_turns + skipped_turns,
    }


def _project_ui_conversation(conversation: dict[str, Any]) -> dict[str, Any]:
    try:
        manifest = export_conversations(
            [conversation],
            vault_root=get_settings().obsidian_vault_path,
            dry_run=False,
        )
        entry = (manifest.get("entries") or [{}])[0]
        return {"ok": True, "action": entry.get("action"), "path": entry.get("path")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}


def _archive_ui_conversation(conversation: dict[str, Any]) -> dict[str, Any]:
    try:
        result = archive_conversation_projection(
            str(conversation.get("id") or ""),
            thread_id=str(conversation.get("thread_id") or conversation.get("id") or ""),
            vault_root=get_settings().obsidian_vault_path,
            dry_run=False,
        )
        return {"ok": True, **result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}


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
    async def scheduled_dreaming() -> bool:
        return await _maybe_run_dreaming(reason="scheduled", force=True)

    scheduler = start_scheduler()
    if scheduler is not None and hasattr(scheduler, "add_job"):
        scheduler.add_job(
            scheduled_dreaming,
            "cron",
            hour=2,
            minute=0,
            id="memory_dreaming",
            replace_existing=True,
        )
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


_PROVIDER_KEY_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
}


def _env_path() -> Path:
    return REPO_ROOT / ".env"


def _set_env_value(key: str, value: str) -> None:
    path = _env_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prefix = f"{key}="
    replacement = f"{key}={value.strip()}"
    updated = False
    next_lines: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            if not updated:
                next_lines.append(replacement)
                updated = True
            continue
        next_lines.append(line)
    if not updated:
        next_lines.append(replacement)
    path.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")
    os.environ[key] = value.strip()
    get_settings.cache_clear()
    try:
        from agent.llm.providers import get_provider_registry

        get_provider_registry.cache_clear()
    except Exception:
        pass


def _x_oauth_file(provider: str) -> Path:
    return REPO_ROOT / "data" / ("xai-oauth.json" if provider == "xai" else "x-api-oauth.json")


def _x_oauth_flow_path(provider: str) -> Path:
    return REPO_ROOT / "data" / "oauth-flows" / f"{provider}.json"


def _save_x_oauth_flow(provider: str, flow: dict[str, Any]) -> None:
    flow_path = _x_oauth_flow_path(provider)
    flow_path.parent.mkdir(parents=True, exist_ok=True)
    flow_path.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
    _oauth_flows[provider] = flow


def _load_x_oauth_flow(provider: str) -> dict[str, Any] | None:
    flow = _oauth_flows.get(provider)
    if flow:
        return flow
    flow_path = _x_oauth_flow_path(provider)
    if not flow_path.exists():
        return None
    try:
        loaded = json.loads(flow_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    created_at = float(loaded.get("created_at") or 0)
    if not created_at or time.time() - created_at > 15 * 60:
        _clear_x_oauth_flow(provider)
        return None
    if isinstance(loaded, dict):
        _oauth_flows[provider] = loaded
        return loaded
    return None


def _clear_x_oauth_flow(provider: str) -> None:
    _oauth_flows.pop(provider, None)
    try:
        _x_oauth_flow_path(provider).unlink(missing_ok=True)
    except OSError:
        pass


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
        _save_x_oauth_flow("xai", {
            "state": state,
            "verifier": verifier,
            "challenge": challenge,
            "redirect_uri": redirect_uri,
            "discovery": discovery,
            "created_at": time.time(),
        })
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
    _save_x_oauth_flow("xapi", {
        "state": state,
        "verifier": verifier,
        "redirect_uri": redirect_uri,
        "client_id": settings.x_api_client_id,
        "created_at": time.time(),
    })
    return XOAuthStartResponse(provider="xapi", authorize_url=authorize_url, status="started")


@router.get("/x/oauth/callback/{provider}")
async def x_oauth_callback(provider: str, code: str = "", state: str = "", error: str = "", error_description: str = "") -> HTMLResponse:
    provider = provider.strip().lower()
    if provider not in {"xai", "xapi"}:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider.")
    if error:
        return HTMLResponse(f"<html><body><h1>X OAuth failed</h1><p>{error_description or error}</p></body></html>", status_code=400)
    flow = _load_x_oauth_flow(provider)
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
            settings = get_settings()
            tokens = await asyncio.to_thread(
                mod.exchange_authorization_code,
                client_id=flow["client_id"],
                client_secret=settings.x_api_client_secret or "",
                code=code,
                redirect_uri=flow["redirect_uri"],
                code_verifier=flow["verifier"],
                timeout_secs=60,
            )
            await asyncio.to_thread(mod.save_oauth_file, _x_oauth_file("xapi"), client_id=flow["client_id"], tokens=tokens)
    except Exception as exc:
        return HTMLResponse(f"<html><body><h1>X OAuth failed</h1><p>{str(exc)}</p></body></html>", status_code=500)
    finally:
        _clear_x_oauth_flow(provider)

    return HTMLResponse(
        "<html><body><h1>X OAuth complete</h1><p>You can close this tab and return to Vellum.</p>"
        "<script>"
        "try {"
        f"  localStorage.setItem('vellum:x-oauth-complete', JSON.stringify({{'provider':'{provider}','ok':true,'at':Date.now()}}));"
        f"  if (window.opener) window.opener.postMessage({{'type':'vellum:x-oauth-complete','provider':'{provider}'}}, '*');"
        "} catch (e) {}"
        "setTimeout(function(){ window.close(); }, 900);"
        "</script></body></html>"
    )


def _spotify_has_credentials() -> bool:
    try:
        saved = _spotify_store().load_tokens()
    except SpotifyAuthError:
        return False
    return bool(saved.get("client_id") and saved.get("access_token") and saved.get("refresh_token"))


@router.get("/plugins/spotify/status", response_model=SpotifyStatusResponse)
async def spotify_oauth_status() -> SpotifyStatusResponse:
    store = _spotify_store()
    try:
        saved = store.load_tokens()
    except SpotifyAuthError:
        return SpotifyStatusResponse(connected=False, status="not_configured")
    try:
        profile = await asyncio.to_thread(_spotify_client().get_profile)
    except SpotifyAuthError:
        return SpotifyStatusResponse(connected=False, status="reauth_required")
    except SpotifyError:
        return SpotifyStatusResponse(connected=True, status="unreachable")
    scopes = str(saved.get("scope") or "").split()
    return SpotifyStatusResponse(
        connected=True,
        status="ready",
        account_name=str(profile.get("display_name") or profile.get("id") or ""),
        product=str(profile.get("product") or ""),
        scopes=scopes,
    )


@router.post("/plugins/spotify/oauth/start", response_model=SpotifyOAuthStartResponse)
async def spotify_oauth_start(request: SpotifyOAuthStartRequest) -> SpotifyOAuthStartResponse:
    client_id = request.client_id.strip()
    if not client_id:
        raise HTTPException(status_code=422, detail="Spotify Client ID is required")
    verifier, challenge = spotify_pkce_pair()
    state = secrets.token_urlsafe(32)
    _spotify_store().save_flow(
        {
            "state": state,
            "code_verifier": verifier,
            "client_id": client_id,
            "redirect_uri": SPOTIFY_REDIRECT_URI,
            "created_at": time.time(),
        }
    )
    return SpotifyOAuthStartResponse(
        authorization_url=spotify_authorization_url(
            client_id=client_id,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            state=state,
            code_challenge=challenge,
        ),
        redirect_uri=SPOTIFY_REDIRECT_URI,
    )


@router.get("/plugins/spotify/oauth/callback")
async def spotify_oauth_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
) -> HTMLResponse:
    if error:
        return HTMLResponse(
            "<html><body><h1>Spotify connection failed</h1><p>Authorization was not completed.</p></body></html>",
            status_code=400,
        )
    if not code:
        return HTMLResponse(
            "<html><body><h1>Spotify connection failed</h1><p>No authorization code was returned.</p></body></html>",
            status_code=400,
        )
    try:
        flow = _spotify_store().consume_flow(state)
    except Exception as exc:
        # Portable plugins are loaded under an isolated module namespace. Tests and
        # embedders may provide the same Spotify store through its package namespace,
        # so matching only by exception class identity is too brittle here.
        if getattr(exc, "code", "") != "spotify_auth_error":
            raise
        return HTMLResponse(
            "<html><body><h1>Spotify connection failed</h1>"
            "<p>The authorization state is invalid or expired. Start the connection again.</p>"
            "</body></html>",
            status_code=400,
        )
    try:
        await asyncio.to_thread(
            _spotify_client().exchange_code,
            client_id=flow["client_id"],
            code=code,
            code_verifier=flow["code_verifier"],
            redirect_uri=flow["redirect_uri"],
        )
    except SpotifyError:
        return HTMLResponse(
            "<html><body><h1>Spotify connection failed</h1><p>Token exchange failed. Start again from Vellum.</p></body></html>",
            status_code=400,
        )
    agent.invalidate()
    return HTMLResponse(
        "<html><body><h1>Spotify connected</h1><p>You can close this tab and return to Vellum.</p>"
        "<script>try {"
        "localStorage.setItem('vellum:spotify-oauth-complete', JSON.stringify({ok:true,at:Date.now()}));"
        "if(window.opener)window.opener.postMessage({type:'vellum:spotify-oauth-complete'},'*');"
        "} catch(e) {} setTimeout(function(){window.close();},900);</script></body></html>"
    )


@router.post("/plugins/spotify/logout")
async def spotify_logout() -> dict[str, bool]:
    _spotify_store().logout()
    agent.invalidate()
    return {"ok": True}


def _spotify_result_or_http(result_text: str) -> dict:
    try:
        result = json.loads(result_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="Unreachable.") from exc
    if result.get("ok"):
        return result.get("data") or {}
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    code = str(error.get("code") or "unreachable")
    message = str(error.get("message") or "Unreachable.")
    if code == "invalid_arguments":
        raise HTTPException(status_code=422, detail=message)
    if code == "spotify_auth_error":
        raise HTTPException(status_code=401, detail=message)
    if code == "rate_limited":
        retry_after = max(1, int(error.get("retry_after") or 1))
        raise HTTPException(status_code=429, detail=message, headers={"Retry-After": str(retry_after)})
    if code in {"premium_required", "no_active_device"}:
        raise HTTPException(status_code=403, detail=message)
    raise HTTPException(status_code=503, detail="Unreachable.")


@router.get("/plugins/spotify/player")
async def spotify_player(details: bool = False) -> dict:
    if not _spotify_has_credentials():
        raise HTTPException(status_code=401, detail="Spotify is not connected")
    try:
        service = _spotify_client()
        player = await asyncio.to_thread(service.get_player)
        if details:
            devices_result, queue_result = await asyncio.gather(
                asyncio.to_thread(service.get_devices),
                asyncio.to_thread(service.get_queue),
            )
            player = {
                **player,
                "devices": devices_result.get("devices", []),
                "queue": queue_result.get("queue", []),
            }
        return player
    except SpotifyRateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except SpotifyAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SpotifyError as exc:
        raise HTTPException(status_code=503, detail="Unreachable.") from exc


@router.post("/plugins/spotify/player/action")
async def spotify_player_action(request: SpotifyPlayerActionRequest) -> dict:
    if not _spotify_has_credentials():
        raise HTTPException(status_code=401, detail="Spotify is not connected")
    payload = request.model_dump(exclude_none=True)
    if request.action == "transfer":
        result = spotify_devices(payload, service=_spotify_client())
    else:
        result = spotify_playback(payload, service=_spotify_client())
    return _spotify_result_or_http(result)


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


async def _run_agent(
    message: str,
    thread_id: str | None,
    model: str | None = None,
    attachments: list[ChatAttachment] | None = None,
) -> ChatResponse:
    clean_message = message.strip()
    if not clean_message:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    active_thread_id = thread_id or get_settings().thread_id

    skill_command = _skill_surface().slash(clean_message)
    if skill_command["handled"]:
        return ChatResponse(
            answer=str(skill_command.get("answer") or ""),
            thread_id=active_thread_id,
            tools=[],
        )
    clean_message = str(skill_command.get("expanded") or clean_message)

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

    memory_recall_intent = _is_memory_recall_request(clean_message, active_thread_id)
    live_result = None if memory_recall_intent else await asyncio.to_thread(_live_dispatcher.maybe_handle, clean_message, active_thread_id)
    delegated_tools: list[str] = []
    delegated_sources: list[Source] = []
    agent_input_message = clean_message
    if live_result is not None and live_result.handled:
        live_sources = _decorate_source_list(list(live_result.sources))
        delegated_tools = list(live_result.tools)
        delegated_sources = [Source(**source) for source in live_sources]
        if _should_passthrough_live_result(live_result):
            answer = live_result.answer or "No response."
            if answer and "blocked for privacy" not in answer.casefold():
                asyncio.create_task(
                    _background_learn(
                        clean_message,
                        answer,
                        active_thread_id,
                        source="x_agent",
                        tools=_memory_tools_from_names(delegated_tools),
                        sources=_memory_source_urls(live_sources),
                        confidence=_memory_confidence(delegated_tools, live_sources),
                        agent_name=str(live_result.agent_name or "VellumAgent"),
                    )
                )
            return ChatResponse(answer=answer, thread_id=active_thread_id, tools=delegated_tools, sources=delegated_sources)
        agent_input_message = _delegated_agent_message(clean_message, live_result, live_sources)

    from agent.skills.usage_intelligence import usage_scope

    skill_usage_scope = usage_scope(clean_message, active_thread_id)
    skill_usage_scope.__enter__()
    direct_skill = re.match(r"Load ([a-z][a-z0-9_-]*) with skill_view", clean_message, re.I)
    if direct_skill:
        skill_usage_scope.activate(direct_skill.group(1), "direct_slash")
    try:
        async with _agent_runtime_lock:
            try:
                await _ensure_model(model)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            await _repair_incomplete_tool_history(active_thread_id)
            agent_message = _agent_message_for_runtime_mode(_with_recent_conversation_context(agent_input_message, active_thread_id))
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": _agent_content_with_attachments(agent_message, attachments)}]},
                config=_thread_config(active_thread_id),
            )
    except asyncio.CancelledError:
        skill_usage_scope.finish("cancelled")
        skill_usage_scope.__exit__(None, None, None)
        raise
    except Exception:
        skill_usage_scope.finish("failed")
        skill_usage_scope.__exit__(None, None, None)
        raise
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
    skill_usage_scope.finish("completed", tool_count=len(tools))
    skill_usage_scope.__exit__(None, None, None)
    seen_source_urls = {source.url for source in delegated_sources if source.url}
    sources = list(delegated_sources)
    for source in _sources_from_messages(messages):
        if source.url and source.url in seen_source_urls:
            continue
        if source.url:
            seen_source_urls.add(source.url)
        sources.append(source)

    if answer and "blocked for privacy" not in answer.casefold():
        asyncio.create_task(
            _background_learn(
                clean_message,
                answer,
                active_thread_id,
                tools=_memory_tools_from_names(tools),
                sources=_memory_source_urls(sources),
                confidence=_memory_confidence(tools, sources),
            )
        )

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


async def _background_learn(
    query: str,
    answer: str,
    thread_id: str = "default",
    source: str = "agent",
    *,
    tools: list[dict[str, Any]] | None = None,
    sources: list[str] | None = None,
    confidence: float | None = None,
    agent_name: str = "VellumAgent",
) -> None:
    try:
        memory_store = getattr(_memory_orchestrator, "store", None)
        memory_settings = memory_store.get_settings() if memory_store is not None else {}
        if memory_settings and (
            not memory_settings.get("memory_enabled", True) or not memory_settings.get("save_new_memories", True)
        ):
            return
        data_class, _reason = classify(query)
        if data_class == DataClass.RED:
            return
        scrubber = PrivacyScrubber()
        clean_query = scrubber.scrub(query)[0] if data_class == DataClass.YELLOW else query
        clean_answer = scrubber.scrub(answer)[0] if data_class == DataClass.YELLOW else answer
        settings = get_settings()
        honcho = HonchoMemory(
            base_url=settings.honcho_base_url,
            app_id=settings.honcho_app_id,
            user_id=settings.honcho_user_id,
        )
        _memory_orchestrator.honcho = honcho
        await asyncio.to_thread(
            _memory_orchestrator.record_turn,
            thread_id=thread_id,
            query=query,
            answer=answer,
            tools=tools or [],
            sources=sources or [],
            confidence=float(confidence if confidence is not None else _memory_confidence([], [])),
            agent_name=agent_name,
            external_query=clean_query,
            external_answer=clean_answer,
        )
        pending = await asyncio.to_thread(
            _memory_orchestrator.extract_memory_candidates,
            thread_id=thread_id,
            user_message=query,
            assistant_message=answer,
            agent_name=agent_name,
        )
        if pending and memory_settings.get("dreaming_enabled", True):
            await _maybe_run_dreaming(reason="background_learn")
        try:
            from agent.skills.learning import SkillLearningWorkflow

            learning = SkillLearningWorkflow(Path(".skills"))
            turn = await asyncio.to_thread(
                learning.record_successful_turn,
                clean_query[:1000],
                complex_task=bool(tools) or len(clean_query) >= 240,
            )
            if turn["review_due"]:
                await asyncio.to_thread(learning.review_candidates)
        except Exception:
            pass
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


def _last_dreaming_run_at() -> datetime | None:
    raw = _dreaming_status.get("last_run")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _maybe_run_dreaming(*, reason: str = "auto", force: bool = False) -> bool:
    store = getattr(_memory_orchestrator, "store", None)
    if store is None:
        return False
    try:
        pending_count = len(store.list_pending())
    except Exception:
        return False
    try:
        settings = store.get_settings()
    except Exception:
        settings = {}
    if not force and not settings.get("dreaming_enabled", True):
        return False
    if not force and pending_count < _DREAMING_MIN_PENDING:
        return False
    last_run = _last_dreaming_run_at()
    if not force and last_run is not None:
        elapsed = (datetime.now(timezone.utc) - last_run).total_seconds()
        if elapsed < _DREAMING_COOLDOWN_SECONDS:
            return False
    if _dreaming_lock.locked():
        return False
    async with _dreaming_lock:
        try:
            pending_count = len(store.list_pending())
        except Exception:
            return False
        if not force and pending_count < _DREAMING_MIN_PENDING:
            return False
        _dreaming_status.update({"status": "running", "reason": reason, "pending_count": pending_count})
        try:
            import_result = await asyncio.to_thread(_import_ui_conversations_to_memory)
            result = await asyncio.to_thread(_memory_orchestrator.run_dreaming)
            result = dict(result)
            result["conversation_import"] = import_result
        except Exception as exc:
            _dreaming_status.update(
                {
                    "status": "error",
                    "last_run": datetime.now(timezone.utc).isoformat(),
                    "reason": reason,
                    "error": str(exc),
                }
            )
            return False
        _dreaming_status.update(
            {
                "status": "completed",
                "last_run": datetime.now(timezone.utc).isoformat(),
                "last_result": result,
                "reason": reason,
                "pending_count": pending_count,
            }
        )
        return True


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


@router.get("/capabilities")
async def capabilities() -> dict[str, Any]:
    return public_capability_contract()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    from agent.skills.curator_runtime import get_curator_runtime

    get_curator_runtime().mark_activity()
    return await _run_agent(request.message, request.thread_id, request.model, request.attachments)


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
    indexed, projection = await asyncio.gather(
        asyncio.to_thread(_index_ui_conversation, record),
        asyncio.to_thread(_project_ui_conversation, record),
    )
    return {"conversation": record, "memory_index": indexed, "obsidian_projection": projection}


@router.patch("/conversations/{conversation_id}")
async def patch_conversation(conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    conversations = _read_ui_conversations()
    for index, conversation in enumerate(conversations):
        if str(conversation.get("id")) == conversation_id:
            updated = _normalize_ui_conversation(conversation_id, {**conversation, **payload})
            conversations[index] = updated
            _write_ui_conversations(conversations)
            indexed, projection = await asyncio.gather(
                asyncio.to_thread(_index_ui_conversation, updated),
                asyncio.to_thread(_project_ui_conversation, updated),
            )
            return {"conversation": updated, "memory_index": indexed, "obsidian_projection": projection}
    raise HTTPException(status_code=404, detail="Conversation not found.")


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict[str, Any]:
    current = _read_ui_conversations()
    deleted = next((item for item in current if str(item.get("id")) == conversation_id), None)
    conversations = [item for item in current if str(item.get("id")) != conversation_id]
    _write_ui_conversations(conversations)
    if not deleted:
        return {"ok": True, "found": False, "obsidian_projection": {"ok": True, "found": False}}
    thread_id = str(deleted.get("thread_id") or deleted.get("id") or conversation_id)
    projection, deleted_fts = await asyncio.gather(
        asyncio.to_thread(_archive_ui_conversation, deleted),
        asyncio.to_thread(_fts5_memory.delete_thread, thread_id),
    )
    await asyncio.to_thread(
        SessionsReader(
            checkpoints_db=REPO_ROOT / "data" / "memory" / "checkpoints.db",
            sessions_db=REPO_ROOT / "data" / "memory" / "sessions.db",
        ).delete,
        thread_id,
    )
    return {
        "ok": True,
        "found": True,
        "deleted_fts_rows": deleted_fts,
        "obsidian_projection": projection,
    }


@router.get("/skills")
async def list_skills_catalog() -> dict[str, Any]:
    return _skill_surface().catalog()


@router.post("/skills/action")
async def mutate_skill(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        result = _skill_surface().action(
            str(payload.get("action") or ""),
            name=str(payload.get("name") or ""),
            confirm=payload.get("confirm") is True,
            **{key: value for key, value in payload.items() if key not in {"action", "name", "confirm"}},
        )
    except (SkillMutationError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "result": result, "catalog": _skill_surface().catalog()}


@router.post("/skills/learn")
async def learn_skill(payload: dict[str, Any]) -> dict[str, Any]:
    from agent.skills.intake import resolve_skill_intake, validate_skill_learn_input

    source = str(payload.get("source") or "").strip()
    if not source:
        raise HTTPException(status_code=400, detail="learn source is required")
    try:
        validate_skill_learn_input(source)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_skill_source", "message": str(exc)},
        ) from exc
    target = resolve_skill_intake(source)
    if target.kind == "marketplace":
        result = json.loads(skill_hub.invoke({
            "action": "install",
            "identifier": target.value,
            "category": str(payload.get("category") or "community"),
            "force": payload.get("force") is True,
        }))
        if result.get("ok") is False:
            raise HTTPException(status_code=400, detail={"code": "skill_intake_failed", "message": result.get("error")})
        mutation_id = str(result.get("id") or "")
        if not mutation_id or not any(item["id"] == mutation_id for item in _skill_surface().mutations.list_pending()):
            raise HTTPException(status_code=500, detail={"code": "pending_not_persisted", "message": "Skill installation was not persisted for approval."})
        return {"ok": True, "mode": "hub_install", "status": "pending", "mutation": result}

    before = {item["id"] for item in _skill_surface().mutations.list_pending()}
    response = await _run_agent(f"/learn {source}", str(payload.get("thread_id") or "skills-hub"))
    pending = _skill_surface().mutations.list_pending()
    created = [item for item in pending if item["id"] not in before]
    if not created:
        raise HTTPException(status_code=422, detail={
            "code": "skill_not_staged",
            "message": "Vellum completed the learning turn but did not create an approval draft.",
            "answer": response.answer,
        })
    return {"ok": True, "mode": "authored", "status": "pending", "mutation": created[-1], "answer": response.answer}


@router.post("/skills/bundles")
async def skill_bundle_action(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(skill_bundles.invoke(payload))


@router.post("/skills/hub")
async def skill_hub_action(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(skill_hub.invoke(payload))


@router.post("/skills/curator")
async def skill_curator_action(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(skill_curator.invoke(payload))


class SkillHubSearchRequest(BaseModel):
    query: str = ""
    source: str | None = None
    category: str = "all"
    ranking: Literal["most-popular", "trending", "most-downloaded"] = "most-popular"
    limit: int = Field(default=20, ge=1, le=100)


class SkillHubMutationRequest(BaseModel):
    identifier: str = ""
    name: str = ""
    category: str = "uncategorized"
    force: bool = False
    confirm: bool = False


class DuplicateDecisionRequest(BaseModel):
    decision: Literal["merge", "replace", "distinct"]
    reason: str = ""


class UsageFeedbackRequest(BaseModel):
    outcome: Literal["corrected", "completed", "failed", "cancelled"]


def _skill_cursor_encode(after: str, view: str, query: str) -> str:
    raw = json.dumps({"after": after, "view": view, "query": query}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _skill_cursor_decode(cursor: str, view: str, query: str) -> str:
    if not cursor:
        return ""
    try:
        loaded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_cursor", "message": "Skill cursor is invalid."}) from exc
    if loaded.get("view") != view or loaded.get("query") != query:
        raise HTTPException(status_code=400, detail={"code": "cursor_scope_mismatch", "message": "Cursor does not match this search."})
    return str(loaded.get("after") or "")


def _etag_response(request: Request, response: Response, payload: Any) -> None:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    etag = f'"{hashlib.sha256(encoded).hexdigest()}"'
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=0, must-revalidate"
    if request.headers.get("if-none-match") == etag:
        response.status_code = 304


@router.get("/skills/v2/overview")
async def skills_v2_overview(request: Request, response: Response) -> dict[str, Any]:
    catalog = _skill_surface().catalog()
    states = catalog["skills"]
    payload = {
        "counts": {name: len(items) for name, items in states.items()},
        "pending": len(catalog["pending_writes"]),
        "installed_from_hub": len(catalog["hub_installed"]),
        "curator": catalog["curator"],
        "write_approval": catalog["write_approval"],
        "external_diagnostics": catalog["external_diagnostics"],
    }
    payload["counts"]["duplicates"] = len(SkillCatalog(_skill_surface().root).duplicate_reviews())
    _etag_response(request, response, payload)
    return payload


@router.get("/skills/v2/catalog")
async def skills_v2_catalog(
    request: Request,
    response: Response,
    view: Literal["installed", "proposed", "retired", "archived", "pending", "duplicates"] = "installed",
    query: str = "",
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str = "",
) -> dict[str, Any]:
    after = _skill_cursor_decode(cursor, view, query)
    surface = _skill_surface()
    if view == "pending":
        items = sorted(surface.mutations.list_pending(), key=lambda item: item["id"])
        if query:
            items = [item for item in items if query.casefold() in f"{item.get('identity','')} {item.get('gist','')}".casefold()]
        if after:
            items = [item for item in items if item["id"] > after]
    elif view == "duplicates":
        items = SkillCatalog(surface.root).duplicate_reviews()
        if after:
            items = [item for item in items if str(item["id"]) > after]
    else:
        state = {"installed": "active", "proposed": "proposed", "retired": "retired", "archived": "archived"}[view]
        items = SkillCatalog(surface.root).search(query, state=state, limit=limit + 1, after=after)
    page = items[:limit]
    next_cursor = None
    if len(items) > limit and page:
        next_cursor = _skill_cursor_encode(str(page[-1].get("normalized_name") or page[-1].get("id") or ""), view, query)
    payload = {"items": page, "next_cursor": next_cursor, "view": view, "source_health": _skills_source_health(surface)}
    _etag_response(request, response, payload)
    return payload


def _skills_source_health(surface: SkillSurfaceService) -> list[dict[str, Any]]:
    health = []
    for source in surface.hub.sources:
        http = getattr(source, "http", None)
        source_id = getattr(source, "source_id", "unknown")
        recent = dict(surface.hub.last_search_health.get(source_id) or {})
        circuit_open = any(value >= 5 for value in getattr(http, "_failures", {}).values())
        health.append({
            "source": source_id,
            "status": "circuit_open" if circuit_open else recent.get("status", "available"),
            "searchable": bool(getattr(source, "searchable", False)),
            "error": recent.get("error"),
            "rate_limit": dict(getattr(source, "quota", {}) or getattr(http, "rate_limit", {}) or {}),
        })
    return health


@router.post("/skills/v2/hub/search")
async def skills_v2_hub_search(request: SkillHubSearchRequest) -> dict[str, Any]:
    from agent.skills.privacy import SkillPrivacyGate

    query = SkillPrivacyGate.marketplace_query(request.query)
    surface = _skill_surface()
    if not query:
        discovery = await asyncio.to_thread(
            surface.hub.discover,
            source_filter=request.source or "all",
            ranking=request.ranking,
            limit_per_section=max(1, min(40, request.limit)),
        )
        items = discovery["items"]
    else:
        discovery = {"sections": [], "ranking": request.ranking, "refreshed_at": None}
        items = await asyncio.to_thread(
            surface.hub.search,
            query,
            source_filter=request.source or "all",
            limit=request.limit,
        )
    if request.category != "all":
        items = [item for item in items if item.get("category") == request.category]
    return {
        "items": items,
        "sections": discovery["sections"],
        "ranking": discovery.get("ranking", request.ranking),
        "refreshed_at": discovery.get("refreshed_at"),
        "source_health": _skills_source_health(surface),
    }


@router.post("/skills/v2/hub/inspect")
async def skills_v2_hub_inspect(request: SkillHubMutationRequest) -> dict[str, Any]:
    try:
        return {"skill": await asyncio.to_thread(_skill_surface().hub.inspect, request.identifier)}
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(status_code=400, detail={"code": "hub_inspection_failed", "message": str(exc)}) from exc


@router.post("/skills/v2/hub/{action}")
async def skills_v2_hub_mutation(action: Literal["install", "update", "uninstall", "import_local"], request: SkillHubMutationRequest) -> dict[str, Any]:
    payload = {
        "action": action,
        "identifier": request.identifier,
        "name": request.name,
        "category": request.category,
        "force": request.force,
        "confirm": request.confirm,
    }
    result = await asyncio.to_thread(lambda: json.loads(skill_hub.invoke(payload)))
    if result.get("ok") is False:
        raise HTTPException(status_code=400, detail={"code": "hub_mutation_failed", "message": result.get("error")})
    return {"result": result}


@router.get("/skills/v2/curator")
async def skills_v2_curator_status() -> dict[str, Any]:
    return _skill_surface().curator.status()


@router.post("/skills/v2/pending/{mutation_id}/approve")
async def skills_v2_pending_approve(mutation_id: str) -> dict[str, Any]:
    try:
        return {"result": _skill_surface().mutations.approve(mutation_id)}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail={"code": "mutation_conflict", "message": str(exc)}) from exc


@router.post("/skills/v2/pending/{mutation_id}/reject")
async def skills_v2_pending_reject(mutation_id: str) -> dict[str, Any]:
    try:
        return {"result": _skill_surface().mutations.reject(mutation_id)}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail={"code": "mutation_conflict", "message": str(exc)}) from exc


@router.post("/skills/v2/duplicates/{review_id}/decision")
async def skills_v2_duplicate_decision(review_id: int, request: DuplicateDecisionRequest) -> dict[str, Any]:
    try:
        return {"result": SkillCatalog(_skill_surface().root).decide_duplicate(review_id, request.decision, distinct_reason=request.reason)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_duplicate_decision", "message": str(exc)}) from exc


@router.post("/skills/v2/usage/{event_id}/feedback")
async def skills_v2_usage_feedback(event_id: str, request: UsageFeedbackRequest) -> dict[str, bool]:
    SkillUsageIntelligence(_skill_surface().root).finish(event_id, outcome=request.outcome)
    return {"ok": True}


@router.get("/skills/{skill_name}")
async def get_skill_detail(skill_name: str, path: str = "") -> dict[str, Any]:
    try:
        return _skill_surface().detail(skill_name, path=path)
    except (KeyError, ValueError, OSError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


@router.get("/agent-profiles")
async def list_agent_profiles() -> dict[str, Any]:
    return {
        "profiles": _profile_registry.public_summaries(),
        "diagnostics": _profile_registry.diagnostics(),
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


def _is_primary_chat_model_stream_event(event: dict[str, Any]) -> bool:
    """Ignore nested provider events already re-emitted by RoutedChatModel.

    LangChain exposes both the routed facade and its nested ChatOpenAI run via
    ``astream_events``. Consuming both duplicates every text and tool-call
    chunk. Synthetic and legacy events may omit ``name``, so keep accepting
    those while preferring the routed facade in production.
    """

    name = str(event.get("name") or "").strip()
    return not name or name == "RoutedChatModel"


def _chunk_tool_call_chunks(chunk: Any) -> list[dict[str, Any]]:
    if chunk is None:
        return []
    raw = chunk.get("tool_call_chunks") if isinstance(chunk, dict) else getattr(chunk, "tool_call_chunks", None)
    if not raw:
        raw = (chunk.get("additional_kwargs", {}) if isinstance(chunk, dict) else getattr(chunk, "additional_kwargs", {}) or {}).get("tool_calls")
    chunks: list[dict[str, Any]] = []
    for index, item in enumerate(raw or []):
        if not isinstance(item, dict):
            continue
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(item.get("name") or function.get("name") or "")
        args = item.get("args")
        if args is None:
            args = function.get("arguments")
        call_id = str(item.get("id") or item.get("tool_call_id") or item.get("index") or index)
        chunks.append({
            "id": call_id,
            "index": int(item.get("index") or index),
            "name": name,
            "delta": str(args or ""),
        })
    return chunks


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


def _response_function_call_arguments_delta(
    *,
    response_id: str,
    thread_id: str,
    item_id: str,
    delta: str,
    output_index: int = 0,
) -> str:
    return _response_event(
        "response.function_call_arguments.delta",
        response_id=response_id,
        thread_id=thread_id,
        item_id=item_id,
        output_index=output_index,
        delta=delta,
    )


def _response_function_call_arguments_done(
    *,
    response_id: str,
    thread_id: str,
    item_id: str,
    arguments: str,
    output_index: int = 0,
) -> str:
    return _response_event(
        "response.function_call_arguments.done",
        response_id=response_id,
        thread_id=thread_id,
        item_id=item_id,
        output_index=output_index,
        arguments=arguments,
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


def _agent_activity_event(
    *,
    response_id: str,
    thread_id: str,
    activity_type: str,
    label: str,
    detail: str = "",
    status: str = "in_progress",
    item_id: str = "",
    name: str = "",
    source: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    return _response_event(
        "agent.activity",
        response_id=response_id,
        thread_id=thread_id,
        activity={
            "id": item_id or _stream_id("activity"),
            "type": activity_type,
            "label": label,
            "detail": detail[:1000],
            "status": status,
            "name": name,
            "source": source,
            "metadata": metadata or {},
            "at": _stream_now(),
        },
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
    "knowledge_wiki": "Maintained your knowledge wiki",
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


_PROVIDER_LABELS = {
    "bbc.com": "BBC",
    "espn.com": "ESPN",
    "fifa.com": "FIFA",
    "formula1.com": "Formula 1",
    "foxsports.com": "FOX Sports",
    "instagram.com": "Instagram",
    "nba.com": "NBA",
    "nbcsports.com": "NBC Sports",
    "reddit.com": "Reddit",
    "skysports.com": "Sky Sports",
    "theguardian.com": "The Guardian",
    "usatoday.com": "USA Today",
    "x.com": "X",
    "twitter.com": "X",
    "yahoo.com": "Yahoo",
    "sports.yahoo.com": "Yahoo Sports",
    "youtube.com": "YouTube",
}


def _provider_label(domain: str, fallback: str = "") -> str:
    clean = (domain or "").lower().removeprefix("www.")
    if clean in _PROVIDER_LABELS:
        return _PROVIDER_LABELS[clean]
    if clean.endswith(".espn.com"):
        return "ESPN"
    if clean.endswith(".yahoo.com"):
        return "Yahoo"
    if clean.endswith(".youtube.com"):
        return "YouTube"
    label = fallback or clean
    return label or "source"


def _decorate_source_record(record: dict[str, Any], *, source_index: int) -> dict[str, Any]:
    url = str(record.get("url") or "")
    domain = str(record.get("domain") or _source_domain(url))
    source_type = str(record.get("source_type") or _source_type(url))
    raw_provider = str(record.get("provider_label") or record.get("provider") or "")
    return {
        **record,
        "domain": domain,
        "source_index": int(record.get("source_index") or source_index),
        "source_type": source_type,
        "favicon_url": str(record.get("favicon_url") or (_favicon_url(domain) if source_type == "web" else "")),
        "provider_label": _provider_label(domain, raw_provider or source_type),
    }


def _decorate_source_list(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_decorate_source_record(record, source_index=index) for index, record in enumerate(records, start=1)]


def _activity_for(name: str, tool_input: Any) -> tuple[str, str]:
    if name == "knowledge_wiki" and isinstance(tool_input, dict):
        action = str(tool_input.get("action") or "").strip().casefold().replace("-", "_")
        label = {
            "status": "Checking your knowledge wiki",
            "query": "Searching your knowledge wiki",
            "read_page": "Reading your knowledge wiki",
            "ingest_source": "Compiling a source into your wiki",
            "upsert_page": "Updating your knowledge wiki",
            "update_overview": "Updating your knowledge overview",
            "rebuild_index": "Rebuilding your knowledge index",
            "lint": "Checking wiki health",
        }.get(action, _ACTIVITY_LABELS["knowledge_wiki"])
        detail = str(tool_input.get("query") or tool_input.get("source_path") or tool_input.get("title") or "")
        return label, detail[:200]
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


def _memory_tools_from_names(tool_names: list[str] | tuple[str, ...] | None) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for name in tool_names or []:
        clean = str(name or "").strip()
        if not clean:
            continue
        tools.append({"name": clean, "output": {"summary": f"{clean} was used during this answer."}})
    return tools


def _memory_source_urls(source_records: list[Any] | tuple[Any, ...] | None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for record in source_records or []:
        url = ""
        if isinstance(record, dict):
            url = str(record.get("url") or "")
        else:
            url = str(getattr(record, "url", "") or "")
        url = url.strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _memory_confidence(tool_names: list[Any] | tuple[Any, ...] | None, source_records: list[Any] | tuple[Any, ...] | None) -> float:
    names = {str(name or "").strip() for name in tool_names or [] if str(name or "").strip()}
    has_sources = bool(_memory_source_urls(source_records))
    if has_sources and names:
        return 0.92
    if has_sources or names.intersection({"web_search", "search_my_notes", "memory_orchestrator", "x_action"}):
        return 0.88
    return 0.7


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


def _recent_conversation_context(clean_message: str, thread_id: str) -> str:
    lowered = clean_message.lower()
    markers = (
        "chat",
        "conversation",
        "discuss",
        "earlier",
        "first",
        "fifth",
        "last",
        "old",
        "older",
        "previous",
        "recall",
        "remember",
        "second",
        "talk about",
        "talked",
        "today",
        "we said",
        "you said",
        "i said",
    )
    recall_intent = any(marker in lowered for marker in markers) or _is_memory_recall_request(clean_message, thread_id)
    if not recall_intent:
        return ""
    conversations = _read_ui_conversations()
    query_terms = _text_terms(clean_message)
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for position, conversation in enumerate(conversations):
        cid = str(conversation.get("thread_id") or conversation.get("id") or "")
        if cid and cid == thread_id:
            continue
        score = _conversation_relevance(conversation, query_terms)
        if score or not query_terms:
            ranked.append((score, position, conversation))

    if not ranked:
        ranked = [(0, position, conversation) for position, conversation in enumerate(conversations[:12])]

    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected_conversations = [conversation for _score, _position, conversation in ranked[:8]]
    lines: list[str] = []
    for conversation in selected_conversations:
        title = str(conversation.get("title") or "Untitled chat")
        cid = str(conversation.get("thread_id") or conversation.get("id") or "")
        messages = conversation.get("messages") if isinstance(conversation.get("messages"), list) else []
        selected = messages
        if query_terms:
            selected = [
                message
                for message in messages
                if query_terms.intersection(_text_terms(_message_text(message)))
            ] or messages[-12:]
        selected = selected[-16:]
        if not selected:
            continue
        lines.append(f"Conversation: {title} (thread: {cid})")
        for message in selected:
            role = _message_role(message)
            text = _message_text(message)
            if text.strip():
                lines.append(f"- {role}: {text.strip()[:700]}")

    try:
        docs = [
            doc
            for doc in _memory_orchestrator.fts5.search(_fts_recall_query(clean_message), limit=12)
            if str(doc.get("thread_id") or "") != str(thread_id)
        ][:8]
    except Exception:
        docs = []
    if docs:
        lines.append("Indexed memory hits:")
        for doc in docs[:6]:
            content = str(doc.get("content") or "").strip()
            if content:
                lines.append(f"- {content[:900]}")
    if not lines:
        return ""
    return (
        "[Recent Vellum conversation context]\n"
        "This is private memory/chat-recall context. Use it before any public search. "
        "If the user asks what happened in previous chats, answer from this context and do not use web_search, SerpAPI, SportsAgent, or public web tools unless the user explicitly asks for fresh/live/current public updates. "
        "Summarize it naturally; do not claim this context is long-term memory unless it was stored there.\n"
        + "\n".join(lines[:80])
    )


def _with_recent_conversation_context(clean_message: str, thread_id: str) -> str:
    context = _recent_conversation_context(clean_message, thread_id)
    if not context:
        return clean_message
    return f"{clean_message}\n\n{context}"


def _with_forced_web_search_context(clean_message: str) -> str:
    return (
        "[Vellum UI mode: Web search is enabled for this turn. Use web_search for public/current facts "
        "before answering. Do not expose raw source lists in the answer body; sources are shown in the UI.]\n\n"
        f"{clean_message}"
    )


def _agent_content_with_attachments(message: str, attachments: list[ChatAttachment] | None) -> str | list[dict[str, Any]]:
    image_parts: list[dict[str, Any]] = []
    for attachment in attachments or []:
        data_url = (attachment.data_url or "").strip()
        mime_type = (attachment.mime_type or "").strip().lower()
        if data_url.startswith("data:image/") or (mime_type.startswith("image/") and data_url.startswith("data:")):
            image_parts.append({"type": "image_url", "image_url": {"url": data_url}})
    if not image_parts:
        return message
    return [{"type": "text", "text": message}, *image_parts]


def _delegated_agent_message(clean_message: str, live_result: LiveAgentResult, live_sources: list[dict[str, Any]]) -> str:
    source_lines = []
    for index, source in enumerate(live_sources, start=1):
        title = str(source.get("provider_label") or source.get("title") or source.get("domain") or source.get("url") or "source")
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
        "using the specialist result as live context. Treat the specialist result and source snippets "
        "as authoritative for current/live facts. If they conflict with your prior knowledge, "
        "follow the specialist result and say so briefly. Mention uncertainty when the specialist "
        "could not fully answer. Preserve exact names, dates, scores, standings, and event order from "
        "the specialist result. Do not replace a live snapshot with older model-memory facts. If the "
        "specialist result includes multiple sources, synthesize across them instead of relying on one. "
        "Use sources internally for factual grounding, but do not add an 'Evidence', 'Sources', "
        "'Sources checked', 'References', or citation-list section in the answer body unless the user "
        "explicitly asks for sources or links. Full source URLs and favicons are already available through "
        "the source/activity button in the UI. Start with the direct answer in one or two sentences. For rankings, "
        "standings, schedules, scores, or statistical lists, include a compact markdown table when the "
        "source data contains enough structured facts. For broad live sports questions, include relevant "
        "latest news, match results, schedule, injury, or tactical context only when it appears in the "
        "specialist result or source snippets; never invent extra fixtures, scores, records, injuries, "
        "or standings to make the answer look complete.\n\n"
        f"User message:\n{clean_message}\n\n"
        f"Specialist tool: {live_result.agent_name}\n"
        f"Specialist status: {live_result.status}\n"
        f"Specialist raw result:\n{live_result.answer}\n\n"
        f"Sources:\n{sources_text}"
    )


def _should_passthrough_live_result(live_result: LiveAgentResult | None) -> bool:
    if live_result is None or not live_result.handled:
        return False
    if live_result.agent_name != "XAgent":
        return False
    return live_result.status in {"answered", "needs_fetch", "blocked", "error"}


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
    attachments: list[ChatAttachment] | None = None,
):
    response_id = _stream_id("resp")
    message_item_id = _stream_id("msg")
    memory_recall_intent = _is_memory_recall_request(clean_message, active_thread_id)
    live_result = None if memory_recall_intent else await asyncio.to_thread(_live_dispatcher.maybe_handle, clean_message, active_thread_id)
    live_sources: list[dict[str, Any]] = []
    delegated_tools: list[str] = []
    subagent_item: dict[str, Any] | None = None
    agent_input_message = clean_message
    yield _response_created(response_id=response_id, thread_id=active_thread_id)
    yield _response_in_progress(response_id=response_id, thread_id=active_thread_id)
    yield _agent_activity_event(
        response_id=response_id,
        thread_id=active_thread_id,
        activity_type="thinking_started",
        label="Thinking...",
        detail=clean_message[:200],
    )
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
            "metadata": {
                "run_id": live_result.run_id,
                "cache_status": live_result.cache_status,
                "cache_reason": live_result.cache_reason,
                "route_source": live_result.route_source,
            },
        }
        yield _agent_activity_event(
            response_id=response_id,
            thread_id=active_thread_id,
            activity_type="sub_agent_started",
            label=f"Calling {live_result.agent_name}...",
            detail=clean_message[:200],
            item_id=str(subagent_item["id"]),
            name=live_result.agent_name,
        )
        yield _response_output_item_added(
            response_id=response_id,
            thread_id=active_thread_id,
            item=subagent_item,
        )
        yield _sse("activity", {"label": f"Routed to {live_result.agent_name}", "detail": clean_message[:200]})
        for activity in live_result.activity_events:
            label = str(activity.get("label") or "Agent activity")
            activity_type = str(activity.get("type") or "tool_call_started")
            name = str(activity.get("name") or "")
            detail = str(activity.get("detail") or "")
            status = str(activity.get("status") or "in_progress")
            yield _agent_activity_event(
                response_id=response_id,
                thread_id=active_thread_id,
                activity_type=activity_type,
                label=label,
                detail=detail,
                status=status,
                item_id=str(activity.get("id") or _stream_id("activity")),
                name=name,
                metadata=dict(activity.get("metadata") or {}),
            )
        suppress_generic_tool_activity = any(
            bool((activity.get("metadata") or {}).get("suppress_generic_tool"))
            for activity in live_result.activity_events
        )
        for tool_name in live_result.tools:
            if suppress_generic_tool_activity:
                yield _sse("tool", {"name": tool_name})
                continue
            tool_item = {
                "id": _stream_id("item"),
                "type": "tool_call",
                "name": tool_name,
                "status": "in_progress",
                "label": f"Used {tool_name}",
                "detail": "",
            }
            yield _agent_activity_event(
                response_id=response_id,
                thread_id=active_thread_id,
                activity_type="tool_call_started",
                label=f"Using {tool_name}...",
                item_id=str(tool_item["id"]),
                name=tool_name,
            )
            yield _response_output_item_added(response_id=response_id, thread_id=active_thread_id, item=tool_item)
            yield _response_output_item_done(response_id=response_id, thread_id=active_thread_id, item=tool_item)
            yield _agent_activity_event(
                response_id=response_id,
                thread_id=active_thread_id,
                activity_type="tool_call_completed",
                label=f"Used {tool_name}",
                status="completed",
                item_id=str(tool_item["id"]),
                name=tool_name,
            )
            yield _sse("tool", {"name": tool_name})
        for source_record in live_sources:
            source_item = {
                "id": _stream_id("item"),
                "type": "source",
                "status": "completed",
                "source": source_record,
            }
            source_label = str(source_record.get("provider_label") or source_record.get("domain") or "source")
            yield _agent_activity_event(
                response_id=response_id,
                thread_id=active_thread_id,
                activity_type="source_discovered",
                label=f"Found {source_label}",
                status="completed",
                item_id=str(source_item["id"]),
                source=source_record,
            )
            yield _agent_activity_event(
                response_id=response_id,
                thread_id=active_thread_id,
                activity_type="source_reading",
                label=f"Reading {source_label}...",
                detail=str(source_record.get("title") or source_record.get("snippet") or ""),
                item_id=str(source_item["id"]) + "-reading",
                source=source_record,
            )
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
        yield _agent_activity_event(
            response_id=response_id,
            thread_id=active_thread_id,
            activity_type="sub_agent_completed",
            label=f"{live_result.agent_name} finished",
            status=subagent_status,
            item_id=str(subagent_item["id"]),
            name=live_result.agent_name,
        )
        if _should_passthrough_live_result(live_result):
            answer = live_result.answer or "No response."
            message_item = {
                "id": message_item_id,
                "type": "message",
                "role": "assistant",
                "status": "in_progress",
            }
            yield _response_output_item_added(
                response_id=response_id,
                thread_id=active_thread_id,
                item=message_item,
            )
            yield _agent_activity_event(
                response_id=response_id,
                thread_id=active_thread_id,
                activity_type="final_answer_started",
                label="Writing answer...",
                item_id=message_item_id,
            )
            if answer:
                yield _response_output_text_delta(
                    response_id=response_id,
                    thread_id=active_thread_id,
                    item_id=message_item_id,
                    delta=answer,
                )
                yield _agent_activity_event(
                    response_id=response_id,
                    thread_id=active_thread_id,
                    activity_type="final_answer_delta",
                    label="Writing answer...",
                    detail=answer[:1000],
                    item_id=message_item_id,
                )
                yield _sse("token", {"text": answer})
            yield _response_output_item_done(
                response_id=response_id,
                thread_id=active_thread_id,
                item=message_item,
            )
            source_models = [Source(**source) for source in live_sources]
            response = ChatResponse(answer=answer, thread_id=active_thread_id, tools=delegated_tools, sources=source_models)
            if answer and "blocked for privacy" not in answer.casefold():
                (
                    asyncio.create_task(
                        _background_learn(
                            clean_message,
                            answer,
                            active_thread_id,
                            source="x_agent",
                            tools=_memory_tools_from_names(delegated_tools),
                            sources=_memory_source_urls(live_sources),
                            confidence=_memory_confidence(delegated_tools, live_sources),
                            agent_name=str(live_result.agent_name or "VellumAgent"),
                        )
                    )
                    if store
                    else _audit_memory_off(active_thread_id, "x_agent")
                )
            yield _agent_activity_event(
                response_id=response_id,
                thread_id=active_thread_id,
                activity_type="final_answer_completed",
                label="Answer written",
                status="completed",
                item_id=message_item_id,
            )
            yield _response_completed(
                response_id=response_id,
                thread_id=active_thread_id,
                answer=answer,
                tools=delegated_tools,
                sources=live_sources,
            )
            yield _sse("final", response.model_dump_json())
            return

    from agent.skills.usage_intelligence import usage_scope

    stream_skill_usage = usage_scope(clean_message, active_thread_id)
    stream_skill_usage.__enter__()
    direct_skill = re.match(r"Load ([a-z][a-z0-9_-]*) with skill_view", clean_message, re.I)
    if direct_skill:
        stream_skill_usage.activate(direct_skill.group(1), "direct_slash")
    async with _agent_runtime_lock:
        answer_parts: list[str] = []
        tool_names: list[str] = list(delegated_tools)
        sources: list[dict] = list(live_sources)
        seen_urls: set[str] = {str(source.get("url") or "") for source in live_sources if source.get("url")}
        active_tool_items: dict[str, dict[str, Any]] = {}
        function_stream_items: dict[str, dict[str, Any]] = {}
        function_stream_args: dict[str, str] = {}
        message_item = {
            "id": message_item_id,
            "type": "message",
            "role": "assistant",
            "status": "in_progress",
        }
        message_item_started = False
        final_answer_started = False
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
            agent_message = _agent_message_for_runtime_mode(_with_recent_conversation_context(agent_input_message, active_thread_id))
            stream = agent.astream_events(
                {"messages": [{"role": "user", "content": _agent_content_with_attachments(agent_message, attachments)}]},
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
                    if not _is_primary_chat_model_stream_event(event):
                        continue
                    chunk = event.get("data", {}).get("chunk")
                    for call_chunk in _chunk_tool_call_chunks(chunk):
                        call_id = str(call_chunk.get("id") or call_chunk.get("index") or "0")
                        delta = str(call_chunk.get("delta") or "")
                        name = str(call_chunk.get("name") or "")
                        item = function_stream_items.get(call_id)
                        if item is None:
                            item = {
                                "id": _stream_id("item"),
                                "type": "function_call",
                                "call_id": call_id,
                                "name": name or "function",
                                "arguments": "",
                                "status": "in_progress",
                                "label": f"Preparing {name or 'function'}",
                                "detail": "",
                            }
                            function_stream_items[call_id] = item
                            function_stream_args[call_id] = ""
                            yield _response_output_item_added(
                                response_id=response_id,
                                thread_id=active_thread_id,
                                item=item,
                            )
                            yield _agent_activity_event(
                                response_id=response_id,
                                thread_id=active_thread_id,
                                activity_type="tool_call_started",
                                label=f"Using {name or 'function'}...",
                                item_id=str(item["id"]),
                                name=name or "function",
                            )
                        if name and item.get("name") in {"", "function"}:
                            item["name"] = name
                            item["label"] = f"Preparing {name}"
                        if delta:
                            function_stream_args[call_id] = function_stream_args.get(call_id, "") + delta
                            item["arguments"] = function_stream_args[call_id]
                            item["detail"] = function_stream_args[call_id][-500:]
                            yield _response_function_call_arguments_delta(
                                response_id=response_id,
                                thread_id=active_thread_id,
                                item_id=str(item["id"]),
                                delta=delta,
                            )
                            yield _agent_activity_event(
                                response_id=response_id,
                                thread_id=active_thread_id,
                                activity_type="tool_call_delta",
                                label=f"Using {item.get('name') or 'function'}...",
                                detail=function_stream_args[call_id][-500:],
                                item_id=str(item["id"]),
                                name=str(item.get("name") or "function"),
                            )
                    text = _chunk_text(chunk)
                    if text:
                        answer_parts.append(text)
                        if not message_item_started:
                            yield _response_output_item_added(
                                response_id=response_id,
                                thread_id=active_thread_id,
                                item=message_item,
                            )
                            message_item_started = True
                        if not final_answer_started:
                            final_answer_started = True
                            yield _agent_activity_event(
                                response_id=response_id,
                                thread_id=active_thread_id,
                                activity_type="final_answer_started",
                                label="Writing answer...",
                                item_id=message_item_id,
                            )
                        yield _response_output_text_delta(
                            response_id=response_id,
                            thread_id=active_thread_id,
                            item_id=message_item_id,
                            delta=text,
                        )
                        yield _agent_activity_event(
                            response_id=response_id,
                            thread_id=active_thread_id,
                            activity_type="final_answer_delta",
                            label="Writing answer...",
                            detail=text,
                            item_id=message_item_id,
                        )
                        yield _sse("token", {"text": text})
                elif kind == "on_tool_start":
                    name = event.get("name") or ""
                    if name:
                        for call_id, item in list(function_stream_items.items()):
                            if item.get("status") == "in_progress" and (not item.get("name") or item.get("name") in {"function", str(name)}):
                                yield _response_function_call_arguments_done(
                                    response_id=response_id,
                                    thread_id=active_thread_id,
                                    item_id=str(item["id"]),
                                    arguments=function_stream_args.get(call_id, ""),
                                )
                                yield _response_output_item_done(
                                    response_id=response_id,
                                    thread_id=active_thread_id,
                                    item=item,
                                )
                                yield _agent_activity_event(
                                    response_id=response_id,
                                    thread_id=active_thread_id,
                                    activity_type="tool_call_completed",
                                    label=f"Used {item.get('name') or 'function'}",
                                    status="completed",
                                    item_id=str(item["id"]),
                                    name=str(item.get("name") or "function"),
                                )
                                item["status"] = "completed"
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
                        lifecycle_type = "memory_retrieved" if str(name) in {"search_my_notes", "memory_search", "obsidian_search"} else "tool_call_started"
                        lifecycle_label = "Using memory..." if lifecycle_type == "memory_retrieved" else f"Using {name}..."
                        yield _agent_activity_event(
                            response_id=response_id,
                            thread_id=active_thread_id,
                            activity_type=lifecycle_type,
                            label=lifecycle_label,
                            detail=detail,
                            item_id=str(item["id"]),
                            name=str(name),
                        )
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
                            source_label = str(record.get("provider_label") or record.get("domain") or "source")
                            yield _agent_activity_event(
                                response_id=response_id,
                                thread_id=active_thread_id,
                                activity_type="source_discovered",
                                label=f"Found {source_label}",
                                status="completed",
                                item_id=str(source_item["id"]),
                                source=record,
                            )
                            yield _agent_activity_event(
                                response_id=response_id,
                                thread_id=active_thread_id,
                                activity_type="source_reading",
                                label=f"Reading {source_label}...",
                                detail=str(record.get("title") or record.get("snippet") or ""),
                                item_id=str(source_item["id"]) + "-reading",
                                source=record,
                            )
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
                        yield _agent_activity_event(
                            response_id=response_id,
                            thread_id=active_thread_id,
                            activity_type="tool_call_completed",
                            label=f"Used {done_item.get('name') or 'tool'}",
                            status="completed",
                            item_id=str(done_item["id"]),
                            name=str(done_item.get("name") or ""),
                        )
                capture_from_stream_event(
                    ledger=_api_ledger,
                    event=event,
                    thread_id=active_thread_id,
                    fallback_model=get_settings().primary_model,
                    source="api",
                )
            for call_id, item in function_stream_items.items():
                if item.get("status") == "in_progress":
                    yield _response_function_call_arguments_done(
                        response_id=response_id,
                        thread_id=active_thread_id,
                        item_id=str(item["id"]),
                        arguments=function_stream_args.get(call_id, ""),
                    )
                    yield _response_output_item_done(
                        response_id=response_id,
                        thread_id=active_thread_id,
                        item=item,
                    )
                    yield _agent_activity_event(
                        response_id=response_id,
                        thread_id=active_thread_id,
                        activity_type="tool_call_completed",
                        label=f"Used {item.get('name') or 'function'}",
                        status="completed",
                        item_id=str(item["id"]),
                        name=str(item.get("name") or "function"),
                    )
                    item["status"] = "completed"
            answer = "".join(answer_parts).strip() or "No response."
            stream_skill_usage.finish("completed", tool_count=len(set(tool_names)))
            stream_skill_usage.__exit__(None, None, None)
            source_models = [Source(**record) for record in sources]
            if voice:
                response: ChatResponse = VoiceChatResponse(answer=answer, thread_id=active_thread_id, tools=tool_names, sources=source_models)
            else:
                response = ChatResponse(answer=answer, thread_id=active_thread_id, tools=tool_names, sources=source_models)
            if answer and "blocked for privacy" not in answer.casefold():
                (
                    asyncio.create_task(
                        _background_learn(
                            clean_message,
                            answer,
                            active_thread_id,
                            source=source,
                            tools=_memory_tools_from_names(tool_names),
                            sources=_memory_source_urls(sources),
                            confidence=_memory_confidence(tool_names, sources),
                        )
                    )
                    if store
                    else _audit_memory_off(active_thread_id, source)
                )
            yield _sse("final", response.model_dump_json())
            if message_item_started:
                yield _response_output_item_done(
                    response_id=response_id,
                    thread_id=active_thread_id,
                    item=message_item,
                )
            yield _agent_activity_event(
                response_id=response_id,
                thread_id=active_thread_id,
                activity_type="final_answer_completed",
                label="Answer written",
                status="completed",
                item_id=message_item_id,
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
            stream_skill_usage.finish("cancelled", tool_count=len(set(tool_names)))
            stream_skill_usage.__exit__(None, None, None)
            await asyncio.shield(_repair_incomplete_tool_history(active_thread_id))
            raise
        except Exception as exc:
            stream_skill_usage.finish("failed", tool_count=len(set(tool_names)))
            stream_skill_usage.__exit__(None, None, None)
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
    from agent.skills.curator_runtime import get_curator_runtime

    get_curator_runtime().mark_activity()
    clean_message = request.message.strip()
    if not clean_message:
        raise HTTPException(status_code=400, detail="message cannot be empty")
    active_thread_id = request.thread_id or get_settings().thread_id

    skill_command = _skill_surface().slash(clean_message)
    if skill_command["handled"]:
        msg = str(skill_command.get("answer") or "")
        final_response = ChatResponse(answer=msg, thread_id=active_thread_id, tools=[])

        async def skill_event():
            yield f"event: meta\ndata: {json.dumps({'thread_id': active_thread_id})}\n\n"
            yield f"event: token\ndata: {json.dumps({'text': msg})}\n\n"
            yield f"event: final\ndata: {final_response.model_dump_json()}\n\n"

        return StreamingResponse(skill_event(), media_type="text/event-stream")
    clean_message = str(skill_command.get("expanded") or clean_message)
    if request.force_web_search:
        clean_message = _with_forced_web_search_context(clean_message)
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
            attachments=request.attachments,
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


class PinMemoryRequest(BaseModel):
    pinned: bool = True


class CreateMemoryRequest(BaseModel):
    text: str
    kind: str = "fact"
    scope: str = "global"
    source_thread_id: str = "manual"
    confidence: float = Field(default=0.95, ge=0, le=1)


class UpdateMemoryRequest(BaseModel):
    text: str | None = None
    kind: str | None = None


class MemorySettingsRequest(BaseModel):
    memory_enabled: bool | None = None
    dreaming_enabled: bool | None = None
    reference_history_enabled: bool | None = None
    save_new_memories: bool | None = None
    auto_archive_enabled: bool | None = None
    use_archived_memories: bool | None = None


@router.get("/memory/summary")
async def memory_summary() -> dict[str, Any]:
    store = _memory_orchestrator.store
    recent_context = await asyncio.to_thread(_memory_orchestrator.fts5.recent_documents, limit=25)
    if store is None:
        return {
            "global_summary": "",
            "saved_memories": [],
            "archived_memories": [],
            "recent_context": recent_context,
            "pending_count": 0,
            "audit_log": [],
            "conversation_import": {"mode": "write_through"},
        }
    return {
        "global_summary": store.global_summary(),
        "saved_memories": store.list_saved(),
        "archived_memories": store.list_archived(),
        "recent_context": recent_context,
        "pending_count": len(store.list_pending()),
        "audit_log": store.audit_log(limit=25),
        "conversation_import": {"mode": "write_through"},
    }


@router.get("/memory/saved")
async def saved_memories() -> dict[str, list[dict[str, Any]]]:
    store = _memory_orchestrator.store
    return {"memories": store.list_saved() if store is not None else []}


@router.get("/memory/archived")
async def archived_memories() -> dict[str, list[dict[str, Any]]]:
    store = _memory_orchestrator.store
    return {"memories": store.list_archived() if store is not None else []}


@router.post("/memory")
async def create_memory(request: CreateMemoryRequest) -> dict[str, Any]:
    store = _memory_orchestrator.store
    if store is None:
        raise HTTPException(status_code=503, detail="memory store unavailable")
    clean_text = request.text.strip()
    if not clean_text:
        raise HTTPException(status_code=422, detail="memory text is required")
    memory_id = await asyncio.to_thread(
        store.save_memory,
        kind=request.kind.strip() or "fact",
        text=clean_text,
        source_thread_id=request.source_thread_id.strip() or "manual",
        confidence=request.confidence,
        scope=request.scope.strip() or "global",
    )
    if getattr(_memory_orchestrator, "fts5", None) is not None:
        await asyncio.to_thread(
            _memory_orchestrator.fts5.add_document,
            content=f"Saved memory: {clean_text}",
            thread_id=request.source_thread_id.strip() or "manual",
            source_paths=[f"memory:{memory_id}"],
        )
    return {"memory": store.get_memory(memory_id)}


@router.get("/memory/settings")
async def memory_settings() -> dict[str, Any]:
    store = _memory_orchestrator.store
    if store is None:
        raise HTTPException(status_code=503, detail="memory store unavailable")
    return {"settings": await asyncio.to_thread(store.get_settings)}


@router.post("/memory/settings")
async def update_memory_settings(request: MemorySettingsRequest) -> dict[str, Any]:
    store = _memory_orchestrator.store
    if store is None:
        raise HTTPException(status_code=503, detail="memory store unavailable")
    patch = request.model_dump(exclude_none=True)
    return {"settings": await asyncio.to_thread(store.update_settings, patch)}


@router.get("/memory/dreaming/status")
async def dreaming_status() -> dict[str, Any]:
    return dict(_dreaming_status)


@router.post("/memory/dreaming/run")
async def run_dreaming() -> dict[str, Any]:
    ok = await _maybe_run_dreaming(reason="manual", force=True)
    if not ok and _dreaming_status.get("status") == "error":
        raise HTTPException(status_code=500, detail=str(_dreaming_status.get("error") or "dreaming failed"))
    result = _dreaming_status.get("last_result") or {
        "new_memories": [],
        "updated_memories": [],
        "archived_memories": [],
        "contradictions": [],
        "global_summary": "",
        "project_summaries": {},
        "audit_log": [],
    }
    return result


@router.post("/memory/import-conversations")
async def import_conversation_memories(limit: int | None = None) -> dict[str, int]:
    return await asyncio.to_thread(_import_ui_conversations_to_memory, limit)


@router.post("/memory/import-obsidian")
async def import_obsidian_memories() -> dict[str, Any]:
    return await asyncio.to_thread(_memory_orchestrator.import_obsidian_memories, get_settings().obsidian_vault_path)


@router.post("/memory/{memory_id}/archive")
async def archive_memory(memory_id: int) -> dict[str, Any]:
    store = _memory_orchestrator.store
    if store is None:
        raise HTTPException(status_code=503, detail="memory store unavailable")
    try:
        return {"memory": await asyncio.to_thread(store.archive, memory_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="memory not found") from exc


@router.post("/memory/{memory_id}/delete")
async def delete_memory(memory_id: int) -> dict[str, bool]:
    store = _memory_orchestrator.store
    if store is None:
        raise HTTPException(status_code=503, detail="memory store unavailable")
    try:
        await asyncio.to_thread(store.delete, memory_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="memory not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/memory/{memory_id}/pin")
async def pin_memory(memory_id: int, request: PinMemoryRequest) -> dict[str, Any]:
    store = _memory_orchestrator.store
    if store is None:
        raise HTTPException(status_code=503, detail="memory store unavailable")
    try:
        return {"memory": await asyncio.to_thread(store.pin, memory_id, request.pinned)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="memory not found") from exc


@router.post("/memory/{memory_id}/update")
async def update_memory(memory_id: int, request: UpdateMemoryRequest) -> dict[str, Any]:
    store = _memory_orchestrator.store
    if store is None:
        raise HTTPException(status_code=503, detail="memory store unavailable")
    try:
        return {
            "memory": await asyncio.to_thread(
                store.update,
                memory_id,
                text=request.text,
                kind=request.kind,
            )
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="memory not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class PrivacyClassifyRequest(BaseModel):
    text: str = ""


@router.post("/privacy/classify")
async def privacy_classify(request: PrivacyClassifyRequest) -> dict[str, str]:
    data_class, reason = classify(request.text)
    return {"class": data_class.value, "reason": reason}


@router.get("/models")
async def list_models() -> dict[str, Any]:
    """Catalog the frontend reads on load to populate the model picker."""
    from agent.llm.providers import configured_provider_keys, get_provider_registry

    registry = get_provider_registry()
    active = registry.current_model()
    provider_keys = configured_provider_keys()
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
        "provider_keys": provider_keys,
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
        memory_orchestrator_plugin_status(_memory_orchestrator).model_dump(),
        agent_reach_plugin_status().model_dump(),
        portable_spotify_status(),
        *[
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
        ],
    ]
    _attach_portable_plugin_metadata(plugins)
    return {"plugins": plugins}


def _attach_portable_plugin_metadata(plugins: list[dict[str, Any]]) -> None:
    try:
        manifests = {manifest.id: manifest for manifest in discover_portable_plugins(REPO_ROOT / "plugins")}
    except Exception:
        manifests = {}
    for plugin in plugins:
        manifest = manifests.get(str(plugin.get("id") or ""))
        if manifest is None:
            continue
        metadata = plugin.setdefault("metadata", {})
        metadata["portable_plugin"] = {
            "id": manifest.id,
            "name": manifest.name,
            "type": manifest.type,
            "category": manifest.category,
            "version": manifest.version,
            "path": manifest.path.as_posix(),
            "capabilities": list(manifest.capabilities),
        }


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
        "provider_keys": {
            "openrouter": bool(settings.openrouter_api_key),
            "openai": bool(settings.openai_api_key),
            "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "google": bool(os.environ.get("GOOGLE_API_KEY")),
        },
    }


@router.post("/settings/provider-key")
async def set_provider_key(request: ProviderKeyRequest, response: Response) -> dict[str, Any]:
    provider = request.provider.strip().lower().replace("-", "_")
    if provider not in _PROVIDER_KEY_ENV:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {request.provider}")
    api_key = request.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key cannot be empty")
    _set_env_value(_PROVIDER_KEY_ENV[provider], api_key)
    reset_routing_runtime()
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Thu, 01 Jul 2027 00:00:00 GMT"
    models = await list_models()
    return {
        "ok": True,
        "provider": provider,
        "configured": True,
        "models": models["models"],
        "active": models["active"],
        "provider_keys": models.get("provider_keys", {}),
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


router.include_router(llm_routing_router)
router.include_router(knowledge_router)
app.include_router(router)


@app.get("/health")
async def root_health() -> dict[str, Any]:
    return await health()
