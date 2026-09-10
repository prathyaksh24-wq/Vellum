"""HTTP contract for the Google Calendar connector."""

from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agent.config import get_settings
from agent.plugins.google_calendar_runtime import (
    GoogleCalendarAPIError,
    GoogleCalendarAuthError,
    google_calendar_authorization_url,
    google_calendar_client,
    google_calendar_pkce_pair,
    google_calendar_scopes,
    google_calendar_service,
    google_calendar_status,
    google_calendar_store,
)
from agent.tools.registry import ToolPermissionError


GOOGLE_CALENDAR_REDIRECT_URI = "http://127.0.0.1:8000"
CALENDAR_STATE_PREFIX = "calendar."
router = APIRouter(prefix="/plugins/google-calendar", tags=["google-calendar"])


class CalendarOAuthStartResponse(BaseModel):
    authorization_url: str
    redirect_uri: str
    scopes: list[str]


class CalendarEventBody(BaseModel):
    calendar_id: str = Field(default="primary", max_length=1024)
    summary: str = Field(min_length=1, max_length=1024)
    start: str
    end: str
    time_zone: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=8192)
    location: str = Field(default="", max_length=1024)
    attendees: list[str] = Field(default_factory=list, max_length=50)
    confirm: bool = False


class CalendarEventPatch(BaseModel):
    calendar_id: str = Field(default="primary", max_length=1024)
    summary: str | None = Field(default=None, max_length=1024)
    start: str | None = None
    end: str | None = None
    time_zone: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=8192)
    location: str | None = Field(default=None, max_length=1024)
    attendees: list[str] | None = Field(default=None, max_length=50)
    confirm: bool = False


class CalendarConfirmBody(BaseModel):
    calendar_id: str = Field(default="primary", max_length=1024)
    confirm: bool = False


class CalendarFreeBusyBody(BaseModel):
    time_min: str
    time_max: str
    calendar_ids: list[str] = Field(default_factory=lambda: ["primary"], min_length=1, max_length=50)


@router.get("/status")
async def status(probe: bool = Query(default=False)) -> dict[str, Any]:
    return await asyncio.to_thread(google_calendar_status, probe=probe)


@router.post("/oauth/start", response_model=CalendarOAuthStartResponse)
async def start_oauth() -> CalendarOAuthStartResponse:
    settings = get_settings()
    client_id = settings.google_calendar_oauth_client_id or settings.youtube_oauth_client_id
    if not client_id:
        raise HTTPException(
            status_code=409,
            detail="Set GOOGLE_CALENDAR_OAUTH_CLIENT_ID or YOUTUBE_OAUTH_CLIENT_ID before connecting Calendar.",
        )
    verifier, challenge = google_calendar_pkce_pair()
    state = CALENDAR_STATE_PREFIX + secrets.token_urlsafe(32)
    google_calendar_store().save_flow({
        "state": state,
        "code_verifier": verifier,
        "redirect_uri": GOOGLE_CALENDAR_REDIRECT_URI,
        "created_at": time.time(),
    })
    url = google_calendar_authorization_url(
        client_id=client_id,
        redirect_uri=GOOGLE_CALENDAR_REDIRECT_URI,
        state=state,
        code_challenge=challenge,
    )
    return CalendarOAuthStartResponse(
        authorization_url=url,
        redirect_uri=GOOGLE_CALENDAR_REDIRECT_URI,
        scopes=list(google_calendar_scopes()),
    )


@router.get("/oauth/callback")
async def oauth_callback(code: str = "", state: str = "", error: str = "") -> HTMLResponse:
    if error:
        return _callback_page(False, "Google Calendar authorization was not completed.", status_code=400)
    if not code:
        return _callback_page(False, "No authorization code was returned.", status_code=400)
    try:
        store = google_calendar_store()
        flow = store.consume_flow(state)
        client = google_calendar_client(store=store)
        await asyncio.to_thread(
            client.exchange_code,
            code=code,
            redirect_uri=str(flow["redirect_uri"]),
            code_verifier=str(flow["code_verifier"]),
        )
        profile = await asyncio.to_thread(client.primary_calendar)
        calendar_settings = await asyncio.to_thread(client.calendar_settings)
        if calendar_settings.get("timezone"):
            profile["timeZone"] = calendar_settings["timezone"]
        await asyncio.to_thread(store.save_profile, profile)
    except (GoogleCalendarAuthError, GoogleCalendarAPIError):
        return _callback_page(False, "Google Calendar connection failed. Start the connection again.", status_code=400)
    return _callback_page(True, "Google Calendar is connected. You can close this tab and return to Vellum.")


@router.delete("/connection")
async def disconnect() -> dict[str, bool]:
    try:
        await asyncio.to_thread(google_calendar_client().disconnect)
    except GoogleCalendarAuthError as exc:
        raise HTTPException(status_code=502, detail="Google Calendar disconnection failed.") from exc
    return {"disconnected": True}


@router.get("/calendars")
async def calendars() -> dict[str, Any]:
    return await _invoke("calendars", {})


@router.get("/events")
async def events(
    time_min: str = Query(...),
    time_max: str = Query(...),
    calendar_id: str = Query(default="primary", max_length=1024),
    query: str = Query(default="", max_length=500),
    max_results: int = Query(default=50, ge=1, le=250),
) -> dict[str, Any]:
    return await _invoke("events", {
        "time_min": time_min,
        "time_max": time_max,
        "calendar_id": calendar_id,
        "query": query,
        "max_results": max_results,
    })


@router.get("/events/{event_id}")
async def event(event_id: str, calendar_id: str = Query(default="primary", max_length=1024)) -> dict[str, Any]:
    return await _invoke("event", {"calendar_id": calendar_id, "event_id": event_id})


@router.post("/free-busy")
async def free_busy(request: CalendarFreeBusyBody) -> dict[str, Any]:
    return await _invoke("free_busy", request.model_dump())


@router.post("/events")
async def create_event(request: CalendarEventBody) -> dict[str, Any]:
    return await _invoke("create_event", request.model_dump())


@router.patch("/events/{event_id}")
async def update_event(event_id: str, request: CalendarEventPatch) -> dict[str, Any]:
    return await _invoke("update_event", {"event_id": event_id, **request.model_dump(exclude_none=True)})


@router.post("/events/{event_id}/delete")
async def delete_event(event_id: str, request: CalendarConfirmBody) -> dict[str, Any]:
    return await _invoke("delete_event", {"event_id": event_id, **request.model_dump()})


async def _invoke(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        handler = getattr(google_calendar_service(), method)
        return await asyncio.to_thread(handler, payload)
    except (GoogleCalendarAuthError, GoogleCalendarAPIError, ToolPermissionError, ValueError) as exc:
        if isinstance(exc, ToolPermissionError):
            status_code = 403
        elif isinstance(exc, GoogleCalendarAuthError):
            status_code = 401
        elif isinstance(exc, ValueError):
            status_code = 422
        else:
            status_code = 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def _callback_page(ok: bool, message: str, *, status_code: int = 200) -> HTMLResponse:
    state = "complete" if ok else "failed"
    value = "true" if ok else "false"
    return HTMLResponse(
        "<html><body>"
        f"<h1>Google Calendar OAuth {state}</h1><p>{message}</p>"
        "<script>try {"
        f"localStorage.setItem('vellum:google-calendar-oauth-complete', JSON.stringify({{'ok':{value},'at':Date.now()}}));"
        f"if (window.opener) window.opener.postMessage({{'type':'vellum:google-calendar-oauth-complete','ok':{value}}}, '*');"
        "} catch (e) {}"
        "if (" + value + ") setTimeout(function(){ window.close(); }, 900);"
        "</script></body></html>",
        status_code=status_code,
    )
