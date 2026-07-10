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


class KnowledgeSourceRequest(BaseModel):
    source_path: str
    title: str
    content: str
    description: str = ""
    links: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    related_pages: list[dict[str, Any]] = Field(default_factory=list)


class KnowledgeLintRequest(BaseModel):
    stale_days: int = Field(default=120, ge=0, le=3650)


class KnowledgeOverviewRequest(BaseModel):
    content: str
    links: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


@router.get("/status")
async def knowledge_status() -> dict[str, Any]:
    return await asyncio.to_thread(get_knowledge_wiki().status)


@router.get("/query")
async def knowledge_query(q: str = Query(min_length=1), limit: int = Query(default=8, ge=1, le=25)) -> dict[str, Any]:
    return await asyncio.to_thread(get_knowledge_wiki().query, q, limit=limit)


@router.get("/pages/{page_ref}")
async def read_knowledge_page(page_ref: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_knowledge_wiki().read_page, page_ref)
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/pages")
async def upsert_knowledge_page(request: KnowledgePageRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_knowledge_wiki().upsert_page, **request.model_dump())
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/ingest")
async def ingest_knowledge_source(request: KnowledgeSourceRequest) -> dict[str, Any]:
    payload = request.model_dump()
    payload["synthesis"] = payload.pop("content")
    try:
        return await asyncio.to_thread(get_knowledge_wiki().ingest_source, **payload)
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/lint")
async def lint_knowledge_wiki(request: KnowledgeLintRequest) -> dict[str, Any]:
    return await asyncio.to_thread(get_knowledge_wiki().lint, stale_days=request.stale_days)


@router.post("/rebuild-index")
async def rebuild_knowledge_index() -> dict[str, Any]:
    return await asyncio.to_thread(get_knowledge_wiki().rebuild_index)


@router.post("/overview")
async def update_knowledge_overview(request: KnowledgeOverviewRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_knowledge_wiki().update_overview, **request.model_dump())
    except KnowledgeWikiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
