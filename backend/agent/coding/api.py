"""HTTP adapter for coding sessions and bounded workspace reads."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.coding.events import event_payload, sse
from agent.coding.models import (
    AccessMode,
    CodingSession,
    CodingSessionCreate,
    CodingTurnLimits,
    CodingTurnRuntime,
    DEFAULT_MAX_PROVIDER_EVENTS,
    DEFAULT_MAX_RUNTIME_SECONDS,
    ProviderName,
    ReasoningEffort,
)
from agent.coding.service import CodingServiceError, CodingSessionService


_LOGGER = logging.getLogger(__name__)


class CodingSessionBody(BaseModel):
    provider: ProviderName
    cwd: str = Field(min_length=1)
    access_mode: AccessMode = AccessMode.read_only
    title: str = ""


class CodingTurnBody(BaseModel):
    prompt: str = Field(min_length=1)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    reasoning_effort: ReasoningEffort | None = None
    max_runtime_seconds: int = Field(default=DEFAULT_MAX_RUNTIME_SECONDS, ge=1, le=24 * 60 * 60)
    max_provider_events: int = Field(default=DEFAULT_MAX_PROVIDER_EVENTS, ge=1, le=100_000)


class CodingSessionCloseBody(BaseModel):
    discard_changes: bool = False


class CodingSessionRewindBody(BaseModel):
    phase: Literal["before", "after"] = "after"
    confirm_discard: bool = False


def create_coding_router(
    *,
    service_provider: Callable[[], CodingSessionService],
    project_roots_provider: Callable[[], list[Path]],
) -> APIRouter:
    """Build the coding HTTP surface around injected runtime ownership."""
    router = APIRouter(prefix="/coding")

    @router.get("/health")
    async def coding_health() -> dict[str, Any]:
        providers = []
        for health in service_provider().health():
            providers.append(
                {
                    "provider": health.provider.value,
                    "available": health.available,
                    "configured": health.configured,
                    "message": health.message,
                    "capabilities": health.capabilities.payload() if health.capabilities else None,
                }
            )
        return {"providers": providers}

    @router.get("/sessions")
    async def coding_sessions() -> dict[str, Any]:
        return {"sessions": [_session_json(session) for session in service_provider().list_sessions()]}

    @router.post("/sessions")
    async def coding_session_create(body: CodingSessionBody) -> dict[str, Any]:
        service = service_provider()
        try:
            _ensure_provider_ready(service, body.provider)
            session = await service.create_session(
                CodingSessionCreate(
                    provider=body.provider,
                    cwd=body.cwd,
                    access_mode=body.access_mode,
                    title=body.title,
                )
            )
        except CodingServiceError as exc:
            raise _http_exception(exc) from exc
        return _session_json(session)

    @router.get("/sessions/{session_id}")
    async def coding_session_get(session_id: str) -> dict[str, Any]:
        try:
            return _session_json(service_provider().get_session(session_id))
        except CodingServiceError as exc:
            raise _http_exception(exc) from exc

    @router.post("/sessions/{session_id}/turns/stream")
    async def coding_turn_stream(session_id: str, body: CodingTurnBody) -> StreamingResponse:
        service = service_provider()
        try:
            session = service.get_session(session_id)
            if session.status == "running":
                raise CodingServiceError("Coding session already has a running turn.")
            _ensure_provider_ready(service, session.provider)
            stream = service.run_turn(
                session_id,
                body.prompt,
                limits=CodingTurnLimits(
                    max_runtime_seconds=body.max_runtime_seconds,
                    max_provider_events=body.max_provider_events,
                ),
                runtime=CodingTurnRuntime(
                    model=body.model,
                    reasoning_effort=body.reasoning_effort,
                ),
            )
            first_event = await anext(stream)
        except CodingServiceError as exc:
            raise _http_exception(exc) from exc
        except StopAsyncIteration:
            async def empty_events():
                if False:
                    yield ""

            return StreamingResponse(empty_events(), media_type="text/event-stream")

        async def events():
            yield sse(first_event)
            try:
                async for event in stream:
                    yield sse(event)
            except CodingServiceError:
                _LOGGER.exception("Coding provider stream failed")
                yield _error_event("Unreachable.")

        return StreamingResponse(events(), media_type="text/event-stream")

    @router.post("/sessions/{session_id}/stop")
    async def coding_session_stop(session_id: str) -> dict[str, Any]:
        try:
            await service_provider().stop_turn(session_id)
        except CodingServiceError as exc:
            raise _http_exception(exc) from exc
        return {"ok": True}

    @router.post("/sessions/{session_id}/close")
    async def coding_session_close(session_id: str, body: CodingSessionCloseBody) -> dict[str, Any]:
        try:
            session = await service_provider().close_session(
                session_id,
                discard_changes=body.discard_changes,
            )
        except CodingServiceError as exc:
            raise _http_exception(exc) from exc
        return _session_json(session)

    @router.get("/sessions/{session_id}/events")
    async def coding_session_events(
        session_id: str,
        after_sequence: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        try:
            return {
                "events": [
                    event_payload(event)
                    for event in service_provider().list_events(session_id, after_sequence=after_sequence)
                ]
            }
        except CodingServiceError as exc:
            raise _http_exception(exc) from exc

    @router.get("/sessions/{session_id}/checkpoints")
    async def coding_session_checkpoints(session_id: str) -> dict[str, Any]:
        try:
            return {
                "checkpoints": [
                    checkpoint.payload(include_patch=False)
                    for checkpoint in service_provider().list_checkpoints(session_id)
                ]
            }
        except CodingServiceError as exc:
            raise _http_exception(exc) from exc

    @router.get("/sessions/{session_id}/checkpoints/{checkpoint_id}")
    async def coding_session_checkpoint(session_id: str, checkpoint_id: str) -> dict[str, Any]:
        try:
            return service_provider().get_checkpoint(session_id, checkpoint_id).payload(include_patch=True)
        except CodingServiceError as exc:
            raise _http_exception(exc) from exc

    @router.post("/sessions/{session_id}/rewind/{checkpoint_id}")
    async def coding_session_rewind(
        session_id: str,
        checkpoint_id: str,
        body: CodingSessionRewindBody,
    ) -> dict[str, Any]:
        try:
            session = await service_provider().rewind_session(
                session_id,
                checkpoint_id,
                phase=body.phase,
                confirm_discard=body.confirm_discard,
            )
        except CodingServiceError as exc:
            raise _http_exception(exc) from exc
        return _session_json(session)

    @router.get("/projects/tree")
    async def coding_project_tree(root: str) -> dict[str, Any]:
        return _project_tree(root, project_roots_provider())

    @router.get("/projects/file")
    async def coding_project_file(root: str, path: str) -> dict[str, Any]:
        return _project_file(root, path, project_roots_provider())

    @router.get("/projects/recent")
    async def coding_recent_projects() -> dict[str, Any]:
        return {"projects": []}

    return router


def _session_json(session: CodingSession) -> dict[str, Any]:
    workspace_kind = getattr(session, "workspace_kind", "direct")
    return {
        "id": session.id,
        "provider": session.provider.value,
        "provider_session_id": session.provider_session_id,
        "cwd": session.cwd,
        "source_cwd": getattr(session, "source_cwd", session.cwd) or session.cwd,
        "workspace_kind": getattr(workspace_kind, "value", str(workspace_kind)),
        "workspace_root": getattr(session, "workspace_root", session.cwd) or session.cwd,
        "workspace_repository_root": getattr(session, "workspace_repository_root", ""),
        "workspace_branch": getattr(session, "workspace_branch", ""),
        "workspace_base_commit": getattr(session, "workspace_base_commit", ""),
        "access_mode": session.access_mode.value,
        "title": session.title,
        "status": session.status,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "tenant_id": getattr(session, "tenant_id", "local"),
        "principal_id": getattr(session, "principal_id", "local-user"),
        "workspace_generation": getattr(session, "workspace_generation", 1),
        "trace_id": getattr(session, "trace_id", ""),
    }


def _hidden_file(name: str) -> bool:
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


def _project_tree(root: str, allowed_roots: list[Path]) -> dict[str, Any]:
    base = Path(root).expanduser().resolve()
    _ensure_project_root(base, allowed_roots)
    items: list[dict[str, Any]] = []
    try:
        paths = sorted(base.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Project root is not readable.") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Project root could not be read.") from exc
    for path in paths:
        if _hidden_file(path.name):
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


def _project_file(root: str, relative_path: str, allowed_roots: list[Path]) -> dict[str, Any]:
    base = Path(root).expanduser().resolve()
    _ensure_project_root(base, allowed_roots)
    if "\x00" in relative_path:
        raise HTTPException(status_code=400, detail="Project file path is invalid.")
    requested = Path(relative_path)
    if requested.is_absolute() or not requested.parts or any(part in {"", ".", ".."} for part in requested.parts):
        raise HTTPException(status_code=400, detail="Project file path is invalid.")
    if any(_hidden_file(part) for part in requested.parts):
        raise HTTPException(status_code=403, detail="Project file is protected.")
    target = (base / requested).resolve()
    if not target.is_relative_to(base):
        raise HTTPException(status_code=403, detail="Project file is outside the workspace.")
    if any(_hidden_file(part) for part in target.relative_to(base).parts):
        raise HTTPException(status_code=403, detail="Project file is protected.")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Project file not found.")
    try:
        size = target.stat().st_size
        limit = 512 * 1024
        with target.open("rb") as handle:
            raw = handle.read(limit)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Project file is not readable.") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Project file could not be read.") from exc
    return {
        "root": str(base),
        "path": target.relative_to(base).as_posix(),
        "content": raw.decode("utf-8", errors="replace"),
        "size": size,
        "truncated": size > limit,
    }


def _ensure_project_root(path: Path, allowed_roots: list[Path]) -> None:
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=404, detail="Project not found.")
    if not any(path == root or path.is_relative_to(root) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Project root is not allowed.")


def _http_exception(exc: CodingServiceError) -> HTTPException:
    message = str(exc)
    cause_message = str(exc.__cause__) if exc.__cause__ is not None else ""
    searchable = f"{message} {cause_message}".casefold()
    if "not found" in searchable:
        return HTTPException(status_code=404, detail=message)
    if (
        "already has a running turn" in searchable
        or "running coding turn" in searchable
        or "session is closed" in searchable
    ):
        return HTTPException(status_code=409, detail=message)
    if (
        "not installed" in searchable
        or "not configured" in searchable
        or "sdk unavailable" in searchable
        or "failed to start" in searchable
    ):
        return HTTPException(status_code=503, detail=message)
    return HTTPException(status_code=400, detail=message)


def _ensure_provider_ready(service: CodingSessionService, provider: ProviderName) -> None:
    for health in service.health():
        if health.provider == provider:
            if not health.available or not health.configured:
                raise CodingServiceError(health.message)
            return
    raise CodingServiceError("Provider is not configured.")


def _error_event(message: str) -> str:
    return f"event: error\ndata: {json.dumps({'type': 'error', 'message': message})}\n\n"
