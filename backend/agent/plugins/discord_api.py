"""Local HTTP contract for the installed Discord bot connector."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from agent.plugins.discord_runtime import (
    DiscordAPIError,
    DiscordAuthError,
    DiscordPermissionError,
    discord_install_url,
    discord_service,
    discord_status,
)
from agent.config import get_settings
from agent.knowledge.runtime import get_knowledge_core
from agent.plugins.discord_package import (
    MAX_ARCHIVE_BYTES,
    DiscordPackageError,
    DiscordPackageImporter,
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


def discord_package_importer() -> DiscordPackageImporter:
    settings = get_settings()
    return DiscordPackageImporter(
        store=get_knowledge_core().store,
        account_id=settings.honcho_user_id,
    )


@router.get("/archive/status")
async def get_discord_archive_status() -> dict[str, Any]:
    return await asyncio.to_thread(discord_package_importer().status)


@router.get("/archive/history")
async def get_discord_archive_history(
    q: str = Query(default="", max_length=500),
    year: int | None = Query(default=None, ge=2000, le=2100),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    return await asyncio.to_thread(
        discord_package_importer().history,
        query=q,
        year=year,
        limit=limit,
    )


@router.post("/archive/import")
async def import_discord_archive(request: Request) -> dict[str, Any]:
    if request.headers.get("x-vellum-confirm", "").casefold() != "true":
        raise HTTPException(status_code=409, detail="Discord archive import requires confirmation.")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
    if content_type not in {"application/zip", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Discord archive must be a ZIP file.")
    try:
        content_length = int(request.headers.get("content-length", "0") or 0)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid content length.") from exc
    if content_length > MAX_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="Discord archive is too large.")

    settings = get_settings()
    temp_root = Path(settings.knowledge_blob_path).parent / "tmp" / "discord-imports"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_path = temp_root / f"{uuid4().hex}.zip"
    written = 0
    try:
        with temp_path.open("xb") as target:
            async for chunk in request.stream():
                written += len(chunk)
                if written > MAX_ARCHIVE_BYTES:
                    raise HTTPException(status_code=413, detail="Discord archive is too large.")
                target.write(chunk)
        if written == 0:
            raise HTTPException(status_code=422, detail="Discord archive is empty.")
        return await asyncio.to_thread(discord_package_importer().run, temp_path)
    except DiscordPackageError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code}) from exc
    finally:
        temp_path.unlink(missing_ok=True)


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
