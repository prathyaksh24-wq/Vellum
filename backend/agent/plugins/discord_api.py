"""Local HTTP contract for the installed Discord bot connector."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
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


class DiscordReactionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emoji: str = Field(min_length=1, max_length=128)
    confirm: StrictBool = False


class DiscordThreadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    confirm: StrictBool = False


class DiscordConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


@router.post("/channels/{channel_id}/attachments")
async def send_discord_attachment(
    channel_id: str,
    file: UploadFile = File(...),
    content: str = Form(default="", max_length=2000),
    confirm: str = Form(default="false", max_length=5),
) -> dict[str, Any]:
    try:
        data = await file.read(10 * 1024 * 1024 + 1)
        return await asyncio.to_thread(
            discord_service().send_attachment,
            {
                "channel_id": channel_id,
                "filename": file.filename or "attachment",
                "content_type": file.content_type or "application/octet-stream",
                "data": data,
                "content": content,
                "confirm": confirm == "true",
            },
        )
    except (DiscordAuthError, DiscordAPIError, DiscordPermissionError, ToolPermissionError, ValueError) as exc:
        raise _discord_http_error(exc) from exc
    finally:
        await file.close()


@router.post("/channels/{channel_id}/messages/{message_id}/reply")
async def reply_to_discord_message(
    channel_id: str,
    message_id: str,
    request: DiscordMessageRequest,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            discord_service().reply_message,
            {
                "channel_id": channel_id,
                "message_id": message_id,
                "content": request.content,
                "confirm": request.confirm,
            },
        )
    except (DiscordAuthError, DiscordAPIError, DiscordPermissionError, ToolPermissionError, ValueError) as exc:
        raise _discord_http_error(exc) from exc


@router.patch("/channels/{channel_id}/messages/{message_id}")
async def edit_own_discord_message(
    channel_id: str,
    message_id: str,
    request: DiscordMessageRequest,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            discord_service().edit_own_message,
            {
                "channel_id": channel_id,
                "message_id": message_id,
                "content": request.content,
                "confirm": request.confirm,
            },
        )
    except (DiscordAuthError, DiscordAPIError, DiscordPermissionError, ToolPermissionError, ValueError) as exc:
        raise _discord_http_error(exc) from exc


@router.post("/channels/{channel_id}/messages/{message_id}/delete")
async def delete_own_discord_message(
    channel_id: str,
    message_id: str,
    request: DiscordConfirmRequest,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            discord_service().delete_own_message,
            {"channel_id": channel_id, "message_id": message_id, "confirm": request.confirm},
        )
    except (DiscordAuthError, DiscordAPIError, DiscordPermissionError, ToolPermissionError, ValueError) as exc:
        raise _discord_http_error(exc) from exc


@router.post("/channels/{channel_id}/messages/{message_id}/reactions")
async def add_discord_reaction(
    channel_id: str,
    message_id: str,
    request: DiscordReactionRequest,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            discord_service().add_reaction,
            {
                "channel_id": channel_id,
                "message_id": message_id,
                "emoji": request.emoji,
                "confirm": request.confirm,
            },
        )
    except (DiscordAuthError, DiscordAPIError, DiscordPermissionError, ToolPermissionError, ValueError) as exc:
        raise _discord_http_error(exc) from exc


@router.post("/channels/{channel_id}/messages/{message_id}/threads")
async def create_discord_thread(
    channel_id: str,
    message_id: str,
    request: DiscordThreadRequest,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            discord_service().create_thread,
            {
                "channel_id": channel_id,
                "message_id": message_id,
                "name": request.name,
                "confirm": request.confirm,
            },
        )
    except (DiscordAuthError, DiscordAPIError, DiscordPermissionError, ToolPermissionError, ValueError) as exc:
        raise _discord_http_error(exc) from exc


@router.post("/channels/{channel_id}/threads/{thread_id}/messages")
async def send_discord_thread_message(
    channel_id: str,
    thread_id: str,
    request: DiscordMessageRequest,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            discord_service().send_thread_message,
            {
                "channel_id": channel_id,
                "thread_id": thread_id,
                "content": request.content,
                "confirm": request.confirm,
            },
        )
    except (DiscordAuthError, DiscordAPIError, DiscordPermissionError, ToolPermissionError, ValueError) as exc:
        raise _discord_http_error(exc) from exc


def _discord_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (DiscordPermissionError, ToolPermissionError)):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, DiscordAuthError):
        return HTTPException(status_code=401, detail="Discord authorization is invalid or missing.")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=502, detail="Discord is unavailable.")
