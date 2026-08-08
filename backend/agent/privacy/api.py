"""HTTP adapter for local disclosure grants."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.llm.routing.runtime import get_routing_runtime
from agent.privacy.disclosure import ProtectionMode


router = APIRouter(prefix="/privacy", tags=["privacy"])


class DisclosureGrantRequest(BaseModel):
    mode: Literal["ask_before_sharing", "full_context"]
    thread_id: str = Field(min_length=1)
    destinations: list[str] = Field(default_factory=lambda: ["openrouter"])
    purposes: list[str] = Field(default_factory=lambda: ["chat"])
    categories: list[str] = Field(default_factory=list)
    ttl_seconds: int = Field(default=300, ge=30, le=3600)


def _grant_store():
    store = get_routing_runtime().broker.grant_store
    if store is None:
        raise HTTPException(status_code=503, detail="disclosure grant store unavailable")
    return store


@router.get("/disclosure-grants")
async def list_disclosure_grants(thread_id: str | None = None) -> dict[str, Any]:
    return {"grants": _grant_store().list_active(thread_id=thread_id)}


@router.post("/disclosure-grants")
async def issue_disclosure_grant(request: DisclosureGrantRequest) -> dict[str, Any]:
    store = _grant_store()
    try:
        grant = store.issue(
            mode=ProtectionMode(request.mode),
            destinations=set(request.destinations),
            purposes=set(request.purposes),
            thread_id=request.thread_id,
            categories=set(request.categories),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=request.ttl_seconds),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"grant": store.public(grant)}


@router.delete("/disclosure-grants/{grant_id}")
async def revoke_disclosure_grant(grant_id: str) -> dict[str, Any]:
    store = _grant_store()
    if not store.revoke(grant_id):
        raise HTTPException(status_code=404, detail="disclosure grant not found")
    return {"ok": True, "grant_id": grant_id}
