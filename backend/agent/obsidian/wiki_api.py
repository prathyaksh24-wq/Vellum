"""Stable API facade for the Obsidian knowledge wiki."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agent.obsidian.wiki import KnowledgeWikiError
from agent.obsidian.wiki_runtime import get_knowledge_wiki


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class KnowledgePageRequest(BaseModel):
    title: str
    page_type: str = "concept"
    content: str
    description: str = ""
    sources: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: str = "draft"
    sensitivity: str = "private"
    source_trust: str = ""
    provenance: list[dict[str, Any] | str] = Field(default_factory=list)
    source_provenance: list[dict[str, Any] | str] = Field(default_factory=list)
    page_id: str = ""
    identity: str = ""
    stable_id: str = ""
    id: str = ""
    replace_sources: bool = False


class KnowledgeSourceRequest(BaseModel):
    source_path: str = ""
    title: str = ""
    content: str = ""
    source_content: str = ""
    description: str = ""
    links: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    related_pages: list[dict[str, Any]] = Field(default_factory=list)
    source_trust: str = ""
    provenance: list[dict[str, Any] | str] = Field(default_factory=list)
    source_provenance: list[dict[str, Any] | str] = Field(default_factory=list)
    approved_source: bool = False
    approved_path: bool = False
    approve_source: bool = False
    approved: bool = False


class KnowledgeLintRequest(BaseModel):
    stale_days: int = Field(default=120, ge=0, le=3650)


class KnowledgeOverviewRequest(BaseModel):
    content: str
    links: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    source_trust: str = ""
    provenance: list[dict[str, Any] | str] = Field(default_factory=list)
    source_provenance: list[dict[str, Any] | str] = Field(default_factory=list)


@router.get("/status")
async def knowledge_status() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_knowledge_wiki().status)
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/query")
async def knowledge_query(q: str = Query(min_length=1), limit: int = Query(default=8, ge=1, le=25)) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_knowledge_wiki().query, q, limit=limit)
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/pages/{page_ref}")
async def read_knowledge_page(page_ref: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_knowledge_wiki().read_page, page_ref)
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/pages/{page_ref}/history")
async def knowledge_page_history(page_ref: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_knowledge_wiki().version_history, page_ref)
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/pages/{page_ref}/history/{version}")
async def read_knowledge_page_version(page_ref: str, version: int) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_knowledge_wiki().read_page_version, page_ref, version)
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/pages")
async def upsert_knowledge_page(request: KnowledgePageRequest) -> dict[str, Any]:
    payload = request.model_dump()
    if payload.get("source_provenance") and not payload.get("provenance"):
        payload["provenance"] = payload["source_provenance"]
    payload.pop("source_provenance", None)
    try:
        return await asyncio.to_thread(get_knowledge_wiki().upsert_page, **payload)
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/ingest")
async def ingest_knowledge_source(request: KnowledgeSourceRequest) -> dict[str, Any]:
    payload = request.model_dump()
    payload["synthesis"] = payload.pop("content")
    if payload.get("source_provenance") and not payload.get("provenance"):
        payload["provenance"] = payload["source_provenance"]
    payload.pop("source_provenance", None)
    payload["approved_source"] = bool(
        payload.get("approved_source") or payload.get("approved_path") or payload.get("approve_source") or payload.pop("approved", False)
    )
    try:
        return await asyncio.to_thread(get_knowledge_wiki().ingest_source, **payload)
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/lint")
async def lint_knowledge_wiki(request: KnowledgeLintRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_knowledge_wiki().lint, stale_days=request.stale_days)
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/rebuild-index")
async def rebuild_knowledge_index() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_knowledge_wiki().rebuild_index)
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# Capability metadata historically advertised this REST-shaped spelling. Keep
# both paths stable while clients migrate.
@router.post("/index/rebuild")
async def rebuild_knowledge_index_compat() -> dict[str, Any]:
    return await rebuild_knowledge_index()


@router.post("/overview")
async def update_knowledge_overview(request: KnowledgeOverviewRequest) -> dict[str, Any]:
    payload = request.model_dump()
    if payload.get("source_provenance"):
        payload["provenance"] = [*payload.get("provenance", []), *payload["source_provenance"]]
    payload.pop("source_provenance", None)
    try:
        return await asyncio.to_thread(get_knowledge_wiki().update_overview, **payload)
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
