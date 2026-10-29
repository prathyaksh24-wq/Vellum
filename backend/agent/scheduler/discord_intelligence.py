"""Incrementally learn allowlisted Discord messages through the shared tool path."""

from __future__ import annotations

import logging

from agent.config import get_settings


logger = logging.getLogger(__name__)


def run_sync() -> dict[str, int]:
    settings = get_settings()
    channel_ids = _csv_ids(settings.discord_allowed_channel_ids)
    if not settings.discord_intelligence_sync_enabled or not settings.discord_bot_token or not channel_ids:
        return {"channels": 0, "messages": 0}
    registry = _registry()
    message_count = 0
    channel_count = 0
    for channel_id in channel_ids:
        try:
            result = registry.invoke(
                "discord.messages",
                {"channel_id": channel_id, "limit": 100},
                agent_name="DiscordAgent",
            )
        except Exception as exc:  # noqa: BLE001 - one channel cannot stop the remaining sync
            logger.warning("[DISCORD] Channel sync failed for %s: %s", channel_id, type(exc).__name__)
            continue
        channel_count += 1
        message_count += len(result.get("items") or [])
    return {"channels": channel_count, "messages": message_count}


def _registry():
    from agent.knowledge.runtime import get_knowledge_core
    from agent.knowledge.tool_observer import KnowledgeToolObserver
    from agent.plugins.discord_runtime import discord_service
    from agent.tools.capabilities.registry import build_shared_tool_registry

    settings = get_settings()
    return build_shared_tool_registry(
        vault_root=settings.obsidian_vault_path,
        discord_service=discord_service(),
        tool_observer=KnowledgeToolObserver(get_knowledge_core()),
    )


def _csv_ids(value: str) -> list[str]:
    return sorted({item for raw in str(value or "").split(",") if (item := raw.strip())})
