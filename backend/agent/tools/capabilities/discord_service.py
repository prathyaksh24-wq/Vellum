from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolPermissionError, ToolRegistry


AccountBackend = Callable[[], dict[str, Any]]
GuildsBackend = Callable[[], list[dict[str, Any]]]
ChannelsBackend = Callable[[str], list[dict[str, Any]]]
MessagesBackend = Callable[[str, int, str], list[dict[str, Any]]]
SendBackend = Callable[[str, str, bool], dict[str, Any]]


class DiscordCapabilityService:
    def __init__(
        self,
        *,
        account_backend: AccountBackend | None = None,
        guilds_backend: GuildsBackend | None = None,
        channels_backend: ChannelsBackend | None = None,
        messages_backend: MessagesBackend | None = None,
        send_backend: SendBackend | None = None,
        allowed_guild_ids: set[str] | frozenset[str] | None = None,
        allowed_channel_ids: set[str] | frozenset[str] | None = None,
        autonomous_channel_ids: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.account_backend = account_backend or self._default_account
        self.guilds_backend = guilds_backend or self._default_guilds
        self.channels_backend = channels_backend or self._default_channels
        self.messages_backend = messages_backend or self._default_messages
        self.send_backend = send_backend or self._default_send
        self.allowed_guild_ids = frozenset(str(value).strip() for value in allowed_guild_ids or set() if str(value).strip())
        self.allowed_channel_ids = frozenset(
            str(value).strip() for value in allowed_channel_ids or set() if str(value).strip()
        )
        self.autonomous_channel_ids = frozenset(
            str(value).strip() for value in autonomous_channel_ids or set() if str(value).strip()
        )
        if not self.autonomous_channel_ids <= self.allowed_channel_ids:
            raise ValueError("Autonomous Discord channels must also be read-allowlisted")

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        read_agents = frozenset({"DiscordAgent", "VellumAgent", "MemoryAgent"})
        registry.register(
            CapabilityRecord(
                name="discord.account",
                namespace="discord",
                access=CapabilityAccess.READ,
                allowed_agents=read_agents,
                stream_label="Checked Discord bot",
                adapter=self.account,
            )
        )
        registry.register(
            CapabilityRecord(
                name="discord.guilds",
                namespace="discord",
                access=CapabilityAccess.READ,
                allowed_agents=read_agents,
                stream_label="Read Discord servers",
                adapter=self.guilds,
            )
        )
        registry.register(
            CapabilityRecord(
                name="discord.channels",
                namespace="discord",
                access=CapabilityAccess.READ,
                allowed_agents=read_agents,
                stream_label="Read Discord channels",
                adapter=self.channels,
            )
        )
        registry.register(
            CapabilityRecord(
                name="discord.messages",
                namespace="discord",
                access=CapabilityAccess.READ,
                allowed_agents=read_agents,
                stream_label="Read Discord messages",
                adapter=self.messages,
            )
        )
        registry.register(
            CapabilityRecord(
                name="discord.send_message",
                namespace="discord",
                access=CapabilityAccess.EXTERNAL_WRITE,
                allowed_agents=frozenset({"DiscordAgent"}),
                stream_label="Sent Discord message",
                adapter=self.send_message,
                requires_confirmation=True,
            )
        )
        return registry

    def account(self, _payload: dict[str, Any]) -> dict[str, Any]:
        account = dict(self.account_backend())
        return {"action": "discord.account", "connected": bool(account.get("id")), "account": account}

    def guilds(self, _payload: dict[str, Any]) -> dict[str, Any]:
        items = [self._guild(item) for item in self.guilds_backend()]
        return {"action": "discord.guilds", "items": [item for item in items if item["id"]]}

    def channels(self, payload: dict[str, Any]) -> dict[str, Any]:
        guild_id = str(payload.get("guild_id") or "").strip()
        if guild_id not in self.allowed_guild_ids:
            raise ToolPermissionError("Discord guild is not allowlisted")
        items = [self._channel(item, guild_id) for item in self.channels_backend(guild_id)]
        return {"action": "discord.channels", "guild_id": guild_id, "items": [item for item in items if item["id"]]}

    def messages(self, payload: dict[str, Any]) -> dict[str, Any]:
        channel_id = self._allowed_channel(payload.get("channel_id"))
        limit = max(1, min(_integer(payload.get("limit"), 20), 100))
        before = str(payload.get("before") or "").strip()
        items = [dict(item) for item in self.messages_backend(channel_id, limit, before)]
        return {"action": "discord.messages", "channel_id": channel_id, "items": items[:limit]}

    def send_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        channel_id = self._allowed_channel(payload.get("channel_id"))
        confirmed = payload.get("confirm") is True
        if not confirmed and channel_id not in self.autonomous_channel_ids:
            raise ToolPermissionError("Discord message requires confirmation")
        content = str(payload.get("content") or "").strip()
        if not content or len(content) > 2000:
            raise ValueError("Discord message content must contain 1 to 2000 characters")
        message = dict(self.send_backend(channel_id, content, confirmed))
        return {
            "action": "discord.send_message",
            "authorization": "standing" if channel_id in self.autonomous_channel_ids and not confirmed else "confirmed",
            "message": message,
        }

    def is_autonomous(self, channel_id: str) -> bool:
        return str(channel_id or "").strip() in self.autonomous_channel_ids

    def _allowed_channel(self, value: Any) -> str:
        channel_id = str(value or "").strip()
        if channel_id not in self.allowed_channel_ids:
            raise ToolPermissionError("Discord channel is not allowlisted")
        return channel_id

    def _guild(self, item: dict[str, Any]) -> dict[str, Any]:
        guild_id = str(item.get("id") or "")
        return {
            "id": guild_id,
            "name": str(item.get("name") or ""),
            "icon": str(item.get("icon") or ""),
            "allowed": guild_id in self.allowed_guild_ids,
        }

    def _channel(self, item: dict[str, Any], guild_id: str) -> dict[str, Any]:
        channel_id = str(item.get("id") or "")
        return {
            "id": channel_id,
            "guild_id": str(item.get("guild_id") or guild_id),
            "name": str(item.get("name") or ""),
            "type": int(item.get("type") or 0),
            "allowed": channel_id in self.allowed_channel_ids,
            "autonomous": channel_id in self.autonomous_channel_ids,
        }

    @staticmethod
    def _default_account() -> dict[str, Any]:
        from agent.plugins.discord_runtime import discord_client

        return discord_client().get_current_user()

    @staticmethod
    def _default_guilds() -> list[dict[str, Any]]:
        from agent.plugins.discord_runtime import discord_client

        return discord_client().list_guilds()

    @staticmethod
    def _default_channels(guild_id: str) -> list[dict[str, Any]]:
        from agent.plugins.discord_runtime import discord_client

        return discord_client().list_channels(guild_id)

    @staticmethod
    def _default_messages(channel_id: str, limit: int, before: str) -> list[dict[str, Any]]:
        from agent.plugins.discord_runtime import discord_client

        return discord_client().list_messages(channel_id, limit=limit, before=before)

    @staticmethod
    def _default_send(channel_id: str, content: str, confirmed: bool) -> dict[str, Any]:
        from agent.plugins.discord_runtime import discord_client

        return discord_client().send_message(channel_id, content, confirmed=confirmed)


def _integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
