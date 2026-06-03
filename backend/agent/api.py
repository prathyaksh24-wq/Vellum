"""HTTP API layer for the personal agent."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import json
from pathlib import Path
import time
from typing import Any

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, Field

from agent.cli.project_commands import (
    CommandResult,
    InvalidCommand,
    handle_project_command,
)
from agent.computer_use.overlay import DesktopActivityOverlay
from agent.computer_use.session import ComputerUseSession, ComputerUseSessionError, NoopOverlay
from agent.computer_use_runtime import computer_use_runtime
from agent.computer_use_workspace import WorkspaceActionError, WorkspaceActionResult, workspace_worker
from agent.config import get_settings
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
_agent_runtime_lock = asyncio.Lock()
_live_dispatcher = LiveAgentDispatcher(vault_root=get_settings().obsidian_vault_path)

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
    voice: bool = False
    store: bool = True  # when False, answer the turn but do NOT persist it (FTS5/Honcho/vault); log an audit breadcrumb instead


class Source(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    domain: str = ""
    fetched_at: str = ""


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
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?",
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
    if live_result is not None and live_result.handled:
        response = ChatResponse(
            answer=live_result.answer,
            thread_id=active_thread_id,
            tools=live_result.tools,
            sources=[Source(**source) for source in live_result.sources],
        )
        if response.answer and "blocked for privacy" not in response.answer.casefold():
            asyncio.create_task(_background_learn(clean_message, response.answer, active_thread_id))
        return response

    async with _agent_runtime_lock:
        try:
            await _ensure_model(model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        await _repair_incomplete_tool_history(active_thread_id)
        agent_message = _agent_message_for_runtime_mode(clean_message)
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
    tools = _tool_call_names(messages)
    sources = _sources_from_messages(messages)

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


def _sse(event: str, payload: dict[str, Any] | str) -> str:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return f"event: {event}\ndata: {data}\n\n"


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
            collected.append(Source(fetched_at=_now_iso(), **record))
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
    live_result = await asyncio.to_thread(_live_dispatcher.maybe_handle, clean_message, active_thread_id)
    if live_result is not None and live_result.handled:
        yield _sse("meta", {"thread_id": active_thread_id})
        yield _sse("activity", {"label": f"Routed to {live_result.agent_name}", "detail": clean_message[:200]})
        for tool_name in live_result.tools:
            yield _sse("tool", {"name": tool_name})
        for source_record in live_result.sources:
            yield _sse("source", source_record)
        if live_result.answer:
            yield _sse("token", {"text": live_result.answer})
        response = VoiceChatResponse(
            answer=live_result.answer,
            thread_id=active_thread_id,
            tools=live_result.tools,
            sources=[Source(**source) for source in live_result.sources],
        ) if voice else ChatResponse(
            answer=live_result.answer,
            thread_id=active_thread_id,
            tools=live_result.tools,
            sources=[Source(**source) for source in live_result.sources],
        )
        if live_result.answer and "blocked for privacy" not in live_result.answer.casefold():
            (asyncio.create_task(_background_learn(clean_message, live_result.answer, active_thread_id, source=source)) if store else _audit_memory_off(active_thread_id, source))
        yield _sse("final", response.model_dump_json())
        if synthesize_audio and live_result.answer:
            async for audio_event in _synthesize_audio_event(live_result.answer):
                yield audio_event
        return

    async with _agent_runtime_lock:
        yield _sse("meta", {"thread_id": active_thread_id})
        answer_parts: list[str] = []
        tool_names: list[str] = []
        sources: list[dict] = []
        seen_urls: set[str] = set()
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
            agent_message = _agent_message_for_runtime_mode(clean_message)
            stream = agent.astream_events(
                {"messages": [{"role": "user", "content": agent_message}]},
                config=_thread_config(active_thread_id),
                version="v2",
            )
            async for event in stream:
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    text = _chunk_text(event.get("data", {}).get("chunk"))
                    if text:
                        answer_parts.append(text)
                        yield _sse("token", {"text": text})
                elif kind == "on_tool_start":
                    name = event.get("name") or ""
                    if name:
                        tool_names.append(str(name))
                        yield _sse("tool", {"name": name})
                        label, detail = _activity_for(str(name), event.get("data", {}).get("input"))
                        yield _sse("activity", {"label": label, "detail": detail})
                elif kind == "on_tool_end":
                    if (event.get("name") or "") == "web_search":
                        output_text = _tool_output_text(event.get("data", {}).get("output"))
                        for record in extract_web_sources(output_text):
                            if record["url"] in seen_urls:
                                continue
                            seen_urls.add(record["url"])
                            record = {**record, "fetched_at": _now_iso()}
                            sources.append(record)
                            yield _sse("source", record)
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
            if synthesize_audio and answer != "No response.":
                async for audio_event in _synthesize_audio_event(answer):
                    yield audio_event
        except asyncio.CancelledError:
            await asyncio.shield(_repair_incomplete_tool_history(active_thread_id))
            raise
        except Exception as exc:
            await _repair_incomplete_tool_history(active_thread_id)
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
