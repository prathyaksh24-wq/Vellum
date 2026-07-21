"""Stable API additions under Vellum's existing /api/knowledge contract."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from agent.knowledge.models import (
    BootstrapRequest,
    ContextPackRequest,
    ObservationActor,
    ObservationInput,
    ProjectionInput,
    SourceItemInput,
    UserSignalInput,
)
from agent.knowledge.runtime import get_knowledge_core


router = APIRouter(prefix="/core", tags=["personal-intelligence"])


@router.get("/status")
async def core_status() -> dict[str, Any]:
    return await asyncio.to_thread(get_knowledge_core().status)


@router.get("/ownership")
async def core_ownership() -> dict[str, Any]:
    return {"ownership": get_knowledge_core().ownership()}


@router.get("/sources")
async def core_sources(
    kind: str = "",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    items = await asyncio.to_thread(get_knowledge_core().store.list_sources, kind=kind, limit=limit, offset=offset)
    return {"sources": items, "count": len(items), "limit": limit, "offset": offset}


@router.post("/sources")
async def core_upsert_source(request: SourceItemInput) -> dict[str, Any]:
    return await asyncio.to_thread(get_knowledge_core().store.upsert_source, request)


@router.get("/observations")
async def core_observations(
    origin: str = "",
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    items = await asyncio.to_thread(get_knowledge_core().store.list_observations, origin=origin, limit=limit)
    return {"observations": items, "count": len(items)}


@router.post("/observations")
async def core_record_observation(request: ObservationInput) -> dict[str, Any]:
    return await asyncio.to_thread(get_knowledge_core().store.record_observation, request)


@router.post("/signals")
async def core_record_signal(request: UserSignalInput) -> dict[str, Any]:
    if request.actor != ObservationActor.USER:
        raise HTTPException(status_code=422, detail="Public signal writes require actor=user.")
    return await asyncio.to_thread(get_knowledge_core().store.record_user_signal, request)


@router.get("/preferences")
async def core_preferences(
    category: str = "",
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    items = await asyncio.to_thread(
        get_knowledge_core().store.list_preferences,
        category=category,
        limit=limit,
    )
    return {"preferences": items, "count": len(items)}


@router.get("/ingestion-jobs")
async def core_ingestion_jobs(
    connector: str = "",
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    items = await asyncio.to_thread(
        get_knowledge_core().store.list_ingestion_jobs,
        connector=connector,
        limit=limit,
    )
    return {"jobs": items, "count": len(items)}


@router.get("/sync-cursors")
async def core_sync_cursors(
    connector: str = "",
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    items = await asyncio.to_thread(
        get_knowledge_core().store.list_sync_cursors,
        connector=connector,
        limit=limit,
    )
    return {"cursors": items, "count": len(items)}


@router.get("/annotations")
async def core_annotations(
    target_id: str = "",
    requires_review: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    items = await asyncio.to_thread(
        get_knowledge_core().store.list_content_annotations,
        target_id=target_id,
        requires_review=requires_review,
        limit=limit,
    )
    return {"annotations": items, "count": len(items)}


@router.post("/projections")
async def core_register_projection(request: ProjectionInput) -> dict[str, Any]:
    return await asyncio.to_thread(get_knowledge_core().store.register_projection, request)


@router.post("/context-packs")
async def core_context_pack(request: ContextPackRequest) -> dict[str, Any]:
    return await asyncio.to_thread(get_knowledge_core().create_context_pack, request)


@router.post("/bootstrap")
async def core_bootstrap(request: BootstrapRequest) -> dict[str, Any]:
    if request.apply and not request.confirm:
        raise HTTPException(status_code=409, detail="Bootstrap apply requires explicit confirmation.")
    return await asyncio.to_thread(get_knowledge_core().bootstrap, request)
