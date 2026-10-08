from __future__ import annotations

from pathlib import Path
from dataclasses import replace

from agent.tools.capabilities.books_service import BooksCapabilityService
from agent.tools.capabilities.calendar_service import CalendarCapabilityService
from agent.tools.capabilities.discord_service import DiscordCapabilityService
from agent.tools.capabilities.mcp_service import McpCapabilityService
from agent.tools.capabilities.memory_service import MemoryCapabilityService
from agent.tools.capabilities.x_service import XCapabilityService
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
from agent.tools.capabilities.spotify_service import SpotifyCapabilityService
from agent.tools.capabilities.kworb_service import KworbCapabilityService
from agent.tools.capabilities.browser_service import BrowserCapabilityService
from agent.tools.registry import ToolInvocationObserver, ToolRegistry


def build_shared_tool_registry(
    *,
    vault_root: Path,
    sessions_db: Path | None = None,
    x_service: XCapabilityService | None = None,
    youtube_service: YoutubeCapabilityService | None = None,
    memory_service: MemoryCapabilityService | None = None,
    books_service: BooksCapabilityService | None = None,
    calendar_service: CalendarCapabilityService | None = None,
    discord_service: DiscordCapabilityService | None = None,
    mcp_service: McpCapabilityService | None = None,
    tool_observer: ToolInvocationObserver | None = None,
) -> ToolRegistry:
    root = Path(vault_root)
    memory_sessions_db = sessions_db or root / "Agent" / "Memory" / "shared-tool-registry-sessions.db"
    services = (
        x_service or XCapabilityService(),
        youtube_service or YoutubeCapabilityService(vault_root=root),
        memory_service or MemoryCapabilityService(vault_root=root, sessions_db=memory_sessions_db),
        mcp_service or McpCapabilityService(),
        books_service or BooksCapabilityService(),
        calendar_service or CalendarCapabilityService(),
        discord_service or _default_discord_service(),
        SpotifyCapabilityService(),
        KworbCapabilityService(),
        BrowserCapabilityService(),
    )
    if tool_observer is None:
        tool_observer = _default_tool_observer()
    registry = ToolRegistry(observer=tool_observer)
    for service in services:
        _copy_records(registry, service.build_registry())
    return registry


def _copy_records(target: ToolRegistry, source: ToolRegistry) -> None:
    for name in source.names():
        record = source.get(name)
        if record.input_schema is None and record.runtime_tool is None:
            record = replace(record, input_schema=_adapter_schema(name))
        target.register(record)


def _adapter_schema(name: str) -> dict:
    """Discovery metadata for the existing dictionary adapters, not a new executor."""
    fields = {
        "calendar.account": [], "calendar.calendars": [],
        "calendar.events": ["time_min", "time_max", "calendar_id", "query", "max_results"],
        "calendar.event": ["calendar_id", "event_id"],
        "calendar.free_busy": ["time_min", "time_max", "calendar_ids"],
        "calendar.availability": ["start", "end", "time_zone", "calendar_id", "event_id"],
        "discord.account": [], "discord.guilds": [], "discord.channels": ["guild_id"],
        "discord.messages": ["channel_id", "limit", "before"],
        "discord.archive_history": ["query", "year", "limit"],
        "youtube.account": [], "youtube.subscriptions": [],
        "youtube.liked_videos": ["max_results"],
        "youtube.takeout_history": ["kind", "limit", "channel"],
        "youtube.takeout_library": ["kind", "limit"],
        "youtube.personal_context": ["query", "limit"],
        "youtube.search_videos": ["query", "max_results"],
        "youtube.fetch_transcript": ["video_id"],
        "x.account": [], "x.bookmarks": ["max_results"], "x.timeline": ["max_results"],
        "x.likes": ["handle", "max_results"], "x.profile": ["handle"],
        "x.user_posts": ["handle", "max_results"], "x.search_posts": ["query", "max_results"],
        "x.read_tweet": ["tweet_id"], "x.replies": ["tweet_id", "max_results"],
        "books.knowledge_query": ["query", "max_chunks", "token_budget"],
        "books.skill_lookup": ["query"],
    }.get(name)
    if fields is None:
        return {"type":"object", "additionalProperties":True}
    properties = {}
    for field in fields:
        properties[field] = {"type":"integer" if field in {"limit","max_results","max_chunks","token_budget","year"} else "string"}
        if field == "calendar_ids": properties[field] = {"type":"array","items":{"type":"string"}}
        if field in {"time_min","time_max","start","end"}: properties[field]["description"] = "ISO 8601 timestamp with timezone offset"
    return {"type":"object", "properties":properties, "additionalProperties":False}


def _default_tool_observer() -> ToolInvocationObserver | None:
    from agent.config import get_settings

    if not get_settings().knowledge_tool_observation_learning:
        return None
    from agent.knowledge.runtime import get_knowledge_core
    from agent.knowledge.tool_observer import KnowledgeToolObserver

    return KnowledgeToolObserver(get_knowledge_core())


def _default_discord_service() -> DiscordCapabilityService:
    from agent.plugins.discord_runtime import discord_service

    return discord_service()
