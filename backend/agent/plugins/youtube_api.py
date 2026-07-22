"""HTTP contract for the read-only YouTube connector."""

from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agent.config import get_settings
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


YOUTUBE_REDIRECT_URI = "http://127.0.0.1:8000"
router = APIRouter(prefix="/plugins/youtube", tags=["youtube"])


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
    settings = get_settings()
    if not settings.youtube_oauth_client_id:
        raise HTTPException(status_code=409, detail="Set YOUTUBE_OAUTH_CLIENT_ID in .env before connecting YouTube.")
    verifier, challenge = youtube_pkce_pair()
    state = secrets.token_urlsafe(32)
    youtube_store().save_flow(
        {
            "state": state,
            "code_verifier": verifier,
            "redirect_uri": YOUTUBE_REDIRECT_URI,
            "created_at": time.time(),
        }
    )
    url = youtube_authorization_url(
        client_id=settings.youtube_oauth_client_id,
        redirect_uri=YOUTUBE_REDIRECT_URI,
        state=state,
        code_challenge=challenge,
    )
    return YouTubeOAuthStartResponse(
        authorization_url=url,
        redirect_uri=YOUTUBE_REDIRECT_URI,
        scopes=["https://www.googleapis.com/auth/youtube.readonly"],
    )


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
    if not youtube_status()["connected"]:
        raise HTTPException(status_code=409, detail="Connect YouTube before synchronizing account data.")
    idempotency_key = request.idempotency_key.strip() or f"manual:{uuid4().hex}"
    try:
        return await asyncio.to_thread(
            YouTubeKnowledgeSync().run,
            idempotency_key=idempotency_key,
            requested_by="user",
        )
    except YouTubeAuthError as exc:
        raise HTTPException(status_code=401, detail="YouTube authorization must be renewed.") from exc
    except YouTubeAPIError as exc:
        raise HTTPException(status_code=502, detail="YouTube synchronization is unavailable.") from exc


@router.delete("/connection")
async def disconnect_youtube() -> dict[str, Any]:
    try:
        await asyncio.to_thread(youtube_client().disconnect)
    except YouTubeAuthError as exc:
        raise HTTPException(status_code=502, detail="YouTube disconnection could not be completed.") from exc
    return {"disconnected": True}


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
