"""Stable API additions under Vellum's existing /api/knowledge contract."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from agent.knowledge.materialization import MaterializationCanaryError
from agent.knowledge.models import (
    BookDocumentRequest,
    BookImportRequest,
    BookImportStatus,
    BootstrapRequest,
    ContextPackRequest,
    MaterializationCanaryRequest,
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


@router.get("/projections")
async def core_projections(
    target: str = "",
    target_ref: str = "",
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    items = await asyncio.to_thread(
        get_knowledge_core().store.list_projections,
        target=target,
        target_ref=target_ref,
        limit=limit,
    )
    return {"projections": items, "count": len(items)}


@router.post("/projections")
async def core_register_projection(request: ProjectionInput) -> dict[str, Any]:
    return await asyncio.to_thread(get_knowledge_core().store.register_projection, request)


@router.post("/context-packs")
async def core_context_pack(request: ContextPackRequest) -> dict[str, Any]:
    return await asyncio.to_thread(get_knowledge_core().create_context_pack, request)


@router.post("/books/epub", response_model=BookImportStatus)
async def core_import_book_epub(
    file: Annotated[UploadFile, File(...)],
    user_id: Annotated[str, Form(min_length=1, max_length=160)],
    rights_attestation_version: Annotated[str, Form(min_length=1, max_length=120)],
    scan_approved: Annotated[bool, Form()],
    pipeline_version: Annotated[
        str,
        Form(min_length=1, max_length=120),
    ] = "book-epub-intake-v1",
    requested_by: Annotated[str, Form(min_length=1, max_length=120)] = "user",
) -> BookImportStatus:
    if scan_approved is not True:
        raise HTTPException(status_code=409, detail="Local malware scan approval is required.")
    core = get_knowledge_core()
    max_bytes = core.book_ingestion.policy.max_asset_bytes
    try:
        if file.size == 0:
            raise HTTPException(status_code=422, detail="EPUB upload is empty.")
        if file.size is not None and file.size > max_bytes:
            raise HTTPException(status_code=413, detail="EPUB upload exceeds the configured limit.")
        content = await file.read(max_bytes + 1)
    finally:
        await file.close()
    if not content:
        raise HTTPException(status_code=422, detail="EPUB upload is empty.")
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="EPUB upload exceeds the configured limit.")
    request = BookImportRequest(
        user_id=user_id,
        rights_attestation_version=rights_attestation_version,
        scan_approved=scan_approved,
        pipeline_version=pipeline_version,
        requested_by=requested_by,
    )
    return await asyncio.to_thread(core.import_book_epub, request, content)


@router.get("/books/imports/{import_id}", response_model=BookImportStatus)
async def core_book_import_status(
    import_id: str,
    user_id: str = Query(min_length=1, max_length=160),
    run_id: str = Query(default="", max_length=160),
) -> BookImportStatus:
    try:
        return await asyncio.to_thread(
            get_knowledge_core().get_book_ingestion_status,
            user_id=user_id,
            import_id=import_id,
            run_id=run_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Book import not found.") from exc


@router.post("/books/documents", response_model=BookImportStatus)
async def core_construct_book_document(request: BookDocumentRequest) -> BookImportStatus:
    try:
        return await asyncio.to_thread(get_knowledge_core().construct_book_document, request)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "BOOK_IMPORT_NOT_FOUND"},
        ) from exc
    except ValueError as exc:
        code = str(exc)
        if code not in {
            "BOOK_NOT_VALIDATED",
            "BOOK_DOCUMENT_NOT_ELIGIBLE",
            "BOOK_DOCUMENT_NONDETERMINISTIC",
            "BOOK_DOCUMENT_RUN_VERSION_MISMATCH",
        }:
            code = "BOOK_DOCUMENT_PUBLICATION_FAILED"
        raise HTTPException(status_code=409, detail={"code": code}) from exc


@router.post("/bootstrap")
async def core_bootstrap(request: BootstrapRequest) -> dict[str, Any]:
    if request.apply and not request.confirm:
        raise HTTPException(status_code=409, detail="Bootstrap apply requires explicit confirmation.")
    return await asyncio.to_thread(get_knowledge_core().bootstrap, request)


@router.post("/materialization-canary")
async def core_materialization_canary(request: MaterializationCanaryRequest) -> dict[str, Any]:
    if request.apply:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "canary_apply_offline",
                "message": "Stop Vellum and run materialize-canary from the local CLI.",
            },
        )
    try:
        result = await asyncio.to_thread(get_knowledge_core().materialize_canary, request)
    except MaterializationCanaryError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "canary_not_ready", "message": str(exc)},
        ) from exc
    if result.get("status") == "rolled_back":
        raise HTTPException(
            status_code=409,
            detail={"code": "canary_rolled_back", "report": result},
        )
    return result
