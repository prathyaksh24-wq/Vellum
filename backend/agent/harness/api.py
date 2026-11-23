"""HTTP adapter for the harness: client plugin payload, live events, approvals, Plugins UI."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent.harness import HarnessError, get_harness, get_plugin_manager


router = APIRouter(prefix="/harness", tags=["harness"])
KEEPALIVE_SECONDS = 15


def _http(exc: HarnessError) -> HTTPException:
    status = 404 if exc.code in {"INSPECT_TARGET_NOT_FOUND", "NOT_INSTALLED"} else 409 if exc.code == "APPROVAL_NOT_PENDING" else 400
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@router.get("/client")
async def harness_client() -> dict[str, Any]:
    harness = await asyncio.to_thread(get_harness)
    return {**harness.client_payload(), "approvals": harness.pending_approvals(), "full_access": harness.full_access}


class ClientManifest(BaseModel):
    slots: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    theme: dict[str, Any] = Field(default_factory=dict)
    revision: int = 0


@router.post("/client/manifest")
async def harness_client_manifest(manifest: ClientManifest) -> dict[str, Any]:
    harness = await asyncio.to_thread(get_harness)
    harness.set_client_manifest(manifest.model_dump())
    return {"ok": True, "revision": harness.revision}


@router.get("/events")
async def harness_events() -> StreamingResponse:
    harness = await asyncio.to_thread(get_harness)
    queue = harness.subscribe()

    async def stream():
        try:
            hello = {"event": "harness/hello", "revision": harness.revision, "approvals": harness.pending_approvals()}
            yield f"data: {json.dumps(hello)}\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(message, default=str)}\n\n"
        finally:
            harness.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ApprovalDecision(BaseModel):
    approved: bool


@router.post("/approvals/{approval_id}")
async def harness_approval(approval_id: str, decision: ApprovalDecision) -> dict[str, Any]:
    harness = await asyncio.to_thread(get_harness)
    try:
        return harness.resolve_approval(approval_id, decision.approved)
    except HarnessError as exc:
        raise _http(exc) from exc


class Permissions(BaseModel):
    full_access: bool


@router.get("/permissions")
async def harness_permissions() -> dict[str, Any]:
    harness = await asyncio.to_thread(get_harness)
    return {"full_access": harness.full_access}


@router.put("/permissions")
async def harness_set_permissions(body: Permissions) -> dict[str, Any]:
    """User-only: the agent has no tool that reaches this."""
    harness = await asyncio.to_thread(get_harness)
    harness.set_full_access(body.full_access)
    return {"full_access": harness.full_access}


@router.get("/bundles/{name:path}/client")
async def harness_bundle_client(name: str) -> FileResponse:
    harness = await asyncio.to_thread(get_harness)
    bundle = next((b for b in harness.installed_bundles() if b.name == name and not b.error), None)
    if bundle is None or bundle.client is None:
        raise HTTPException(status_code=404, detail="No client module for that bundle.")
    return FileResponse(bundle.client, media_type="text/javascript", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- Plugins UI (human caller)


@router.get("/plugins")
async def harness_plugins(offset: int = 0, limit: int = 100) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(lambda: get_plugin_manager().list_plugins(offset=offset, limit=limit))
    except HarnessError as exc:
        raise _http(exc) from exc


@router.get("/bundles")
async def harness_bundles(offset: int = 0, limit: int = 100) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(lambda: get_plugin_manager().list_bundles(offset=offset, limit=limit))
    except HarnessError as exc:
        raise _http(exc) from exc


class SetEnabled(BaseModel):
    enabled: bool


@router.post("/plugins/{entry_id}")
async def harness_set_plugin(entry_id: str, body: SetEnabled) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(lambda: get_plugin_manager().set_plugin(entry_id, body.enabled))
    except HarnessError as exc:
        raise _http(exc) from exc


@router.post("/bundles/{name:path}/enabled")
async def harness_set_bundle(name: str, body: SetEnabled) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(lambda: get_plugin_manager().set_bundle(name, body.enabled))
    except HarnessError as exc:
        raise _http(exc) from exc


@router.delete("/bundles/{name:path}")
async def harness_remove_bundle(name: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(lambda: get_plugin_manager().remove_bundle(name))
    except HarnessError as exc:
        raise _http(exc) from exc


class EditConfig(BaseModel):
    config: dict[str, Any]


@router.put("/config/{entry_id}")
async def harness_edit_config(entry_id: str, body: EditConfig) -> dict[str, Any]:
    """The config editor for human-operated controls (for example the model picker)."""
    try:
        return await asyncio.to_thread(lambda: get_harness().edit_config(entry_id, lambda _current: body.config))
    except HarnessError as exc:
        raise _http(exc) from exc
