"""Host-owned Discord server and channel authorization."""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import DiscordPermissionError


@dataclass(frozen=True)
class DiscordAccessPolicy:
    allowed_guild_ids: frozenset[str] = field(default_factory=frozenset)
    allowed_channel_ids: frozenset[str] = field(default_factory=frozenset)
    autonomous_channel_ids: frozenset[str] = field(default_factory=frozenset)

    def __init__(
        self,
        *,
        allowed_guild_ids: set[str] | frozenset[str] | None = None,
        allowed_channel_ids: set[str] | frozenset[str] | None = None,
        autonomous_channel_ids: set[str] | frozenset[str] | None = None,
    ) -> None:
        guilds = _identifiers(allowed_guild_ids)
        channels = _identifiers(allowed_channel_ids)
        object.__setattr__(self, "allowed_guild_ids", guilds)
        object.__setattr__(self, "allowed_channel_ids", channels)
        object.__setattr__(self, "autonomous_channel_ids", frozenset())

    def require_guild(self, guild_id: str) -> str:
        clean = _identifier(guild_id)
        if clean not in self.allowed_guild_ids:
            raise DiscordPermissionError("Discord guild is not allowlisted")
        return clean

    def require_channel(self, channel_id: str) -> str:
        clean = _identifier(channel_id)
        if clean not in self.allowed_channel_ids:
            raise DiscordPermissionError("Discord channel is not allowlisted")
        return clean

    def authorize_send(self, channel_id: str, *, confirmed: bool = False) -> str:
        clean = self.require_channel(channel_id)
        if not confirmed:
            raise DiscordPermissionError("Discord message requires confirmation")
        return clean

    def is_autonomous(self, channel_id: str) -> bool:
        self.require_channel(channel_id)
        return False


def _identifiers(values: set[str] | frozenset[str] | None) -> frozenset[str]:
    return frozenset(_identifier(value) for value in values or set())


def _identifier(value: str) -> str:
    clean = str(value or "").strip()
    if not clean or not clean.isdigit() or len(clean) > 32:
        raise DiscordPermissionError("Discord identifier is invalid")
    return clean
