"""HTTP contract for the read-only YouTube connector."""

from __future__ import annotations

import asyncio
import secrets
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agent.config import get_settings
from agent.knowledge.runtime import get_knowledge_core
from agent.plugins.youtube_channel_identity import YouTubeChannelIdentityService
from agent.plugins.youtube_contract import YOUTUBE_REDIRECT_URI
from agent.plugins.youtube_intelligence import YouTubeIntelligenceService
from agent.plugins.youtube_runtime import (
    YouTubeAPIError,
    YouTubeAuthError,
    YouTubeKnowledgeSync,
    youtube_authorization_url,
    youtube_client,
    youtube_pkce_pair,
    youtube_status,
    youtube_store,
)


router = APIRouter(prefix="/plugins/youtube", tags=["youtube"])


def _controls() -> Any:
    # Load plugin contributions only after this compatibility module is initialized.
    # Importing them first would make app_actions.runtime re-enter a partial module.
    from agent.plugins.youtube_controls import YouTubeControlService

    return YouTubeControlService(
        settings_provider=get_settings,
        status_provider=youtube_status,
        store_provider=youtube_store,
        client_provider=youtube_client,
        sync_factory=YouTubeKnowledgeSync,
        pkce_provider=youtube_pkce_pair,
        authorization_url_provider=youtube_authorization_url,
        state_factory=lambda: secrets.token_urlsafe(32),
        knowledge_core_provider=get_knowledge_core,
        intelligence_factory=YouTubeIntelligenceService,
    )


class YouTubeStatusResponse(BaseModel):
    configured: bool
    connected: bool
    status: str
    account_label: str
    channel_id: str = ""
    channel_title: str = ""
    scopes: list[str] = Field(default_factory=list)


class YouTubeOAuthStartResponse(BaseModel):
    authorization_url: str
    redirect_uri: str
    scopes: list[str]


class YouTubeSyncRequest(BaseModel):
    idempotency_key: str = Field(default="", max_length=500)


@router.get("/status", response_model=YouTubeStatusResponse)
async def get_youtube_status() -> YouTubeStatusResponse:
    return YouTubeStatusResponse(**youtube_status())


@router.post("/oauth/start", response_model=YouTubeOAuthStartResponse)
async def start_youtube_oauth() -> YouTubeOAuthStartResponse:
    controls = _controls()
    from agent.plugins.contributions import PluginContributionActionError

    try:
        return YouTubeOAuthStartResponse(**await asyncio.to_thread(controls.start_connection))
    except PluginContributionActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/oauth/callback")
async def youtube_oauth_callback(
    code: str = "",
    state: str = "",
    error: str = "",
) -> HTMLResponse:
    if error:
        return _callback_page(False, "YouTube authorization was not completed.", status_code=400)
    if not code:
        return _callback_page(False, "No authorization code was returned.", status_code=400)
    try:
        store = youtube_store()
        flow = store.consume_flow(state)
        client = youtube_client(store=store)
        await asyncio.to_thread(
            client.exchange_code,
            code=code,
            redirect_uri=str(flow["redirect_uri"]),
            code_verifier=str(flow["code_verifier"]),
        )
        profile = await asyncio.to_thread(client.get_my_channel)
        await asyncio.to_thread(store.save_profile, profile)
    except (YouTubeAuthError, YouTubeAPIError):
        return _callback_page(False, "YouTube connection failed. Start the connection again from Vellum.", status_code=400)
    return _callback_page(True, "YouTube is connected. You can close this tab and return to Vellum.")


@router.post("/sync")
async def sync_youtube(request: YouTubeSyncRequest) -> dict[str, Any]:
    controls = _controls()
    from agent.plugins.contributions import PluginContributionActionError

    try:
        return await asyncio.to_thread(controls.sync, idempotency_key=request.idempotency_key)
    except PluginContributionActionError as exc:
        status_code = 401 if exc.code == "YOUTUBE_REAUTH_REQUIRED" else 502 if exc.code == "YOUTUBE_SYNC_UNAVAILABLE" else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/intelligence")
async def get_youtube_intelligence(
    limit: int = Query(default=20, ge=1, le=100),
    query: str = Query(default="", max_length=500),
) -> dict[str, Any]:
    intelligence = YouTubeIntelligenceService(get_knowledge_core().store)
    return await asyncio.to_thread(intelligence.snapshot, limit=limit, query=query)


@router.get("/intelligence/status")
async def get_youtube_intelligence_status() -> dict[str, Any]:
    intelligence = YouTubeIntelligenceService(get_knowledge_core().store)
    return await asyncio.to_thread(intelligence.status)


@router.get("/intelligence/identities")
async def get_youtube_identity_profile(
    limit: int = Query(default=100, ge=1, le=100),
) -> dict[str, Any]:
    identities = YouTubeChannelIdentityService(get_knowledge_core().store)
    return await asyncio.to_thread(identities.profile, limit=limit)


@router.post("/intelligence/rebuild")
async def rebuild_youtube_intelligence(
    mode: Literal["backfill", "incremental"] | None = Query(default=None),
) -> dict[str, Any]:
    controls = _controls()
    from agent.plugins.contributions import PluginContributionActionError

    try:
        return await asyncio.to_thread(controls.rebuild_intelligence, mode=mode or "")
    except PluginContributionActionError as exc:
        raise HTTPException(
            status_code=500,
            detail="YouTube intelligence rebuild failed.",
        ) from exc


@router.delete("/connection")
async def disconnect_youtube() -> dict[str, Any]:
    controls = _controls()
    from agent.plugins.contributions import PluginContributionActionError

    try:
        return await asyncio.to_thread(controls.disconnect)
    except PluginContributionActionError as exc:
        raise HTTPException(status_code=502, detail="YouTube disconnection could not be completed.") from exc


def _callback_page(ok: bool, message: str, *, status_code: int = 200) -> HTMLResponse:
    status = "complete" if ok else "failed"
    event = "true" if ok else "false"
    return HTMLResponse(
        "<html><body>"
        f"<h1>YouTube OAuth {status}</h1><p>{message}</p>"
        "<script>"
        "try {"
        f"localStorage.setItem('vellum:youtube-oauth-complete', JSON.stringify({{'ok':{event},'at':Date.now()}}));"
        f"if (window.opener) window.opener.postMessage({{'type':'vellum:youtube-oauth-complete','ok':{event}}}, '*');"
        "} catch (e) {}"
        "if (" + event + ") setTimeout(function(){ window.close(); }, 900);"
        "</script></body></html>",
        status_code=status_code,
    )
