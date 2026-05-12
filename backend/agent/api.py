"""HTTP API layer for the personal agent."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.config import get_settings
from agent.graph.agent import agent
from agent.memory.fts5 import FTS5Memory
from agent.memory.honcho_client import HonchoMemory
from agent.obsidian.ingester import VaultIngester
from agent.obsidian.watcher import start_vault_watcher
from agent.privacy.classifier import DataClass, classify
from agent.privacy.scrubber import PrivacyScrubber
from agent.scheduler.digest import start_scheduler
from agent.telemetry.hooks import capture_from_invoke_result, capture_from_stream_event
from agent.telemetry.usage_ledger import UsageLedger
from agent.tools.obsidian_write import store_qa_pair

_api_ledger = UsageLedger(Path("data/memory/usage.db"))
_fts5_memory = FTS5Memory()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    thread_id: str
    tools: list[str] = Field(default_factory=list)


class ReindexResponse(BaseModel):
    chunks: int


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


async def _run_agent(message: str, thread_id: str | None) -> ChatResponse:
    clean_message = message.strip()
    if not clean_message:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    active_thread_id = thread_id or get_settings().thread_id
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
    return await _run_agent(request.message, request.thread_id)


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


app.include_router(router)


@app.get("/health")
async def root_health() -> dict[str, Any]:
    return await health()
