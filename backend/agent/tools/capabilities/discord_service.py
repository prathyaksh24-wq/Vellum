from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolPermissionError, ToolRegistry


AccountBackend = Callable[[], dict[str, Any]]
GuildsBackend = Callable[[], list[dict[str, Any]]]
ChannelsBackend = Callable[[str], list[dict[str, Any]]]
MessagesBackend = Callable[[str, int, str], list[dict[str, Any]]]
SendBackend = Callable[[str, str, bool], dict[str, Any]]
ReplyBackend = Callable[[str, str, str, bool], dict[str, Any]]
EditBackend = Callable[[str, str, str, bool], dict[str, Any]]
DeleteBackend = Callable[[str, str, bool], dict[str, Any]]
ReactionBackend = Callable[[str, str, str, bool], dict[str, Any]]
ThreadBackend = Callable[[str, str, str, bool], dict[str, Any]]
ThreadMessageBackend = Callable[[str, str, str, bool], dict[str, Any]]
AttachmentBackend = Callable[[str, str, str, bytes, str, bool], dict[str, Any]]


class DiscordCapabilityService:
    def __init__(
        self,
        *,
        account_backend: AccountBackend | None = None,
        guilds_backend: GuildsBackend | None = None,
        channels_backend: ChannelsBackend | None = None,
        messages_backend: MessagesBackend | None = None,
        send_backend: SendBackend | None = None,
        reply_backend: ReplyBackend | None = None,
        edit_backend: EditBackend | None = None,
        delete_backend: DeleteBackend | None = None,
        reaction_backend: ReactionBackend | None = None,
        thread_backend: ThreadBackend | None = None,
        thread_message_backend: ThreadMessageBackend | None = None,
        attachment_backend: AttachmentBackend | None = None,
        allowed_guild_ids: set[str] | frozenset[str] | None = None,
        allowed_channel_ids: set[str] | frozenset[str] | None = None,
        autonomous_channel_ids: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.account_backend = account_backend or self._default_account
        self.guilds_backend = guilds_backend or self._default_guilds
        self.channels_backend = channels_backend or self._default_channels
        self.messages_backend = messages_backend or self._default_messages
        self.send_backend = send_backend or self._default_send
        self.reply_backend = reply_backend or self._default_reply
        self.edit_backend = edit_backend or self._default_edit
        self.delete_backend = delete_backend or self._default_delete
        self.reaction_backend = reaction_backend or self._default_reaction
        self.thread_backend = thread_backend or self._default_thread
        self.thread_message_backend = thread_message_backend or self._default_thread_message
        self.attachment_backend = attachment_backend or self._default_attachment
        self.allowed_guild_ids = frozenset(str(value).strip() for value in allowed_guild_ids or set() if str(value).strip())
        self.allowed_channel_ids = frozenset(
            str(value).strip() for value in allowed_channel_ids or set() if str(value).strip()
        )
        self.autonomous_channel_ids = frozenset()

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
        for name, label, adapter in (
            ("discord.reply_message", "Replied to Discord message", self.reply_message),
            ("discord.edit_own_message", "Edited Vellum Discord message", self.edit_own_message),
            ("discord.delete_own_message", "Deleted Vellum Discord message", self.delete_own_message),
            ("discord.add_reaction", "Reacted to Discord message", self.add_reaction),
            ("discord.create_thread", "Created Discord thread", self.create_thread),
            ("discord.send_thread_message", "Sent Discord thread message", self.send_thread_message),
            ("discord.send_attachment", "Sent Discord attachment", self.send_attachment),
        ):
            registry.register(
                CapabilityRecord(
                    name=name,
                    namespace="discord",
                    access=CapabilityAccess.EXTERNAL_WRITE,
                    allowed_agents=frozenset({"DiscordAgent"}),
                    stream_label=label,
                    adapter=adapter,
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
        channel_id, confirmed = self._authorized_channel(payload)
        content = str(payload.get("content") or "").strip()
        if not content or len(content) > 2000:
            raise ValueError("Discord message content must contain 1 to 2000 characters")
        message = dict(self.send_backend(channel_id, content, confirmed))
        return {
            "action": "discord.send_message",
            "authorization": "confirmed",
            "message": message,
        }

    def reply_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        channel_id, confirmed = self._authorized_channel(payload)
        message = dict(self.reply_backend(
            channel_id,
            self._id(payload.get("message_id"), "message"),
            self._content(payload.get("content")),
            confirmed,
        ))
        return {"action": "discord.reply_message", "authorization": "confirmed", "message": message}

    def edit_own_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        channel_id, confirmed = self._authorized_channel(payload)
        message = dict(self.edit_backend(
            channel_id,
            self._id(payload.get("message_id"), "message"),
            self._content(payload.get("content")),
            confirmed,
        ))
        return {"action": "discord.edit_own_message", "authorization": "confirmed", "message": message}

    def delete_own_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        channel_id, confirmed = self._authorized_channel(payload)
        result = dict(self.delete_backend(
            channel_id,
            self._id(payload.get("message_id"), "message"),
            confirmed,
        ))
        return {"action": "discord.delete_own_message", "authorization": "confirmed", "message": result}

    def add_reaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        channel_id, confirmed = self._authorized_channel(payload)
        emoji = str(payload.get("emoji") or "").strip()
        if not emoji or len(emoji) > 128:
            raise ValueError("Discord reaction emoji is invalid")
        result = dict(self.reaction_backend(
            channel_id,
            self._id(payload.get("message_id"), "message"),
            emoji,
            confirmed,
        ))
        return {"action": "discord.add_reaction", "authorization": "confirmed", "reaction": result}

    def create_thread(self, payload: dict[str, Any]) -> dict[str, Any]:
        channel_id, confirmed = self._authorized_channel(payload)
        name = str(payload.get("name") or "").strip()
        if not name or len(name) > 100:
            raise ValueError("Discord thread name must contain 1 to 100 characters")
        thread = dict(self.thread_backend(
            channel_id,
            self._id(payload.get("message_id"), "message"),
            name,
            confirmed,
        ))
        return {"action": "discord.create_thread", "authorization": "confirmed", "thread": thread}

    def send_thread_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        parent_channel_id, confirmed = self._authorized_channel(payload)
        message = dict(self.thread_message_backend(
            parent_channel_id,
            self._id(payload.get("thread_id"), "thread"),
            self._content(payload.get("content")),
            confirmed,
        ))
        return {"action": "discord.send_thread_message", "authorization": "confirmed", "message": message}

    def send_attachment(self, payload: dict[str, Any]) -> dict[str, Any]:
        channel_id, confirmed = self._authorized_channel(payload)
        filename = str(payload.get("filename") or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
        data = payload.get("data")
        if not filename or len(filename) > 255:
            raise ValueError("Discord attachment filename is invalid")
        if not isinstance(data, bytes) or not data or len(data) > 10 * 1024 * 1024:
            raise ValueError("Discord attachment must contain 1 byte to 10 MiB")
        content = str(payload.get("content") or "").strip()
        if len(content) > 2000:
            raise ValueError("Discord message content must contain at most 2000 characters")
        message = dict(self.attachment_backend(
            channel_id,
            filename,
            str(payload.get("content_type") or "application/octet-stream"),
            data,
            content,
            confirmed,
        ))
        return {"action": "discord.send_attachment", "authorization": "confirmed", "message": message}

    def is_autonomous(self, channel_id: str) -> bool:
        return str(channel_id or "").strip() in self.autonomous_channel_ids

    def _allowed_channel(self, value: Any) -> str:
        channel_id = str(value or "").strip()
        if channel_id not in self.allowed_channel_ids:
            raise ToolPermissionError("Discord channel is not allowlisted")
        return channel_id

    def _authorized_channel(self, payload: dict[str, Any]) -> tuple[str, bool]:
        channel_id = self._allowed_channel(payload.get("channel_id"))
        confirmed = payload.get("confirm") is True
        if not confirmed:
            raise ToolPermissionError("Discord action requires confirmation")
        return channel_id, confirmed

    @staticmethod
    def _id(value: Any, label: str) -> str:
        identifier = str(value or "").strip()
        if not identifier or not identifier.isdigit() or len(identifier) > 32:
            raise ValueError(f"Discord {label} identifier is invalid")
        return identifier

    @staticmethod
    def _content(value: Any) -> str:
        content = str(value or "").strip()
        if not content or len(content) > 2000:
            raise ValueError("Discord message content must contain 1 to 2000 characters")
        return content

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
            "autonomous": False,
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

    @staticmethod
    def _default_reply(channel_id: str, message_id: str, content: str, confirmed: bool) -> dict[str, Any]:
        from agent.plugins.discord_runtime import discord_client

        return discord_client().reply_message(channel_id, message_id, content, confirmed=confirmed)

    @staticmethod
    def _default_edit(channel_id: str, message_id: str, content: str, confirmed: bool) -> dict[str, Any]:
        from agent.plugins.discord_runtime import discord_client

        return discord_client().edit_own_message(channel_id, message_id, content, confirmed=confirmed)

    @staticmethod
    def _default_delete(channel_id: str, message_id: str, confirmed: bool) -> dict[str, Any]:
        from agent.plugins.discord_runtime import discord_client

        return discord_client().delete_own_message(channel_id, message_id, confirmed=confirmed)

    @staticmethod
    def _default_reaction(channel_id: str, message_id: str, emoji: str, confirmed: bool) -> dict[str, Any]:
        from agent.plugins.discord_runtime import discord_client

        return discord_client().add_reaction(channel_id, message_id, emoji, confirmed=confirmed)

    @staticmethod
    def _default_thread(channel_id: str, message_id: str, name: str, confirmed: bool) -> dict[str, Any]:
        from agent.plugins.discord_runtime import discord_client

        return discord_client().create_thread(channel_id, message_id, name, confirmed=confirmed)

    @staticmethod
    def _default_thread_message(
        parent_channel_id: str,
        thread_id: str,
        content: str,
        confirmed: bool,
    ) -> dict[str, Any]:
        from agent.plugins.discord_runtime import discord_client

        return discord_client().send_thread_message(
            parent_channel_id,
            thread_id,
            content,
            confirmed=confirmed,
        )

    @staticmethod
    def _default_attachment(
        channel_id: str,
        filename: str,
        content_type: str,
        data: bytes,
        content: str,
        confirmed: bool,
    ) -> dict[str, Any]:
        from agent.plugins.discord_runtime import discord_client

        return discord_client().send_attachment(
            channel_id,
            filename=filename,
            content_type=content_type,
            data=data,
            content=content,
            confirmed=confirmed,
        )


def _integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
