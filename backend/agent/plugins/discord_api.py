"""Local HTTP contract for the installed Discord bot connector."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from agent.plugins.discord_runtime import (
    DiscordAPIError,
    DiscordAuthError,
    DiscordPermissionError,
    discord_install_url,
    discord_service,
    discord_status,
)
from agent.tools.registry import ToolPermissionError


router = APIRouter(prefix="/plugins/discord", tags=["discord"])


class DiscordMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=2000)
    confirm: StrictBool = False


@router.get("/status")
async def get_discord_status() -> dict[str, Any]:
    return await asyncio.to_thread(discord_status, probe=True)


@router.get("/install")
async def get_discord_install() -> dict[str, str]:
    try:
        return {"authorization_url": discord_install_url()}
    except DiscordAuthError as exc:
        raise HTTPException(status_code=409, detail="Set DISCORD_APPLICATION_ID before installing Discord.") from exc


@router.get("/guilds")
async def get_discord_guilds() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(discord_service().guilds, {})
    except (DiscordAuthError, DiscordAPIError) as exc:
        raise _discord_http_error(exc) from exc


@router.get("/guilds/{guild_id}/channels")
async def get_discord_channels(guild_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(discord_service().channels, {"guild_id": guild_id})
    except (DiscordAuthError, DiscordAPIError, DiscordPermissionError, ToolPermissionError) as exc:
        raise _discord_http_error(exc) from exc


@router.get("/channels/{channel_id}/messages")
async def get_discord_messages(
    channel_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    before: str = Query(default="", max_length=32),
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            discord_service().messages,
            {"channel_id": channel_id, "limit": limit, "before": before},
        )
    except (DiscordAuthError, DiscordAPIError, DiscordPermissionError, ToolPermissionError) as exc:
        raise _discord_http_error(exc) from exc


@router.post("/channels/{channel_id}/messages")
async def send_discord_message(channel_id: str, request: DiscordMessageRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            discord_service().send_message,
            {"channel_id": channel_id, "content": request.content, "confirm": request.confirm},
        )
    except (DiscordAuthError, DiscordAPIError, DiscordPermissionError, ToolPermissionError) as exc:
        raise _discord_http_error(exc) from exc


def _discord_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (DiscordPermissionError, ToolPermissionError)):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, DiscordAuthError):
        return HTTPException(status_code=401, detail="Discord authorization is invalid or missing.")
    return HTTPException(status_code=502, detail="Discord is unavailable.")
