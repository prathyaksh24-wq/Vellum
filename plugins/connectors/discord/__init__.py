"""Portable Discord connector registration."""

from __future__ import annotations

from . import auth, client, errors, policy


DiscordAccessPolicy = policy.DiscordAccessPolicy
DiscordClient = client.DiscordClient

CAPABILITIES = [
    "discord.account",
    "discord.guilds",
    "discord.channels",
    "discord.messages",
    "discord.send_message",
    "discord.reply_message",
    "discord.edit_own_message",
    "discord.delete_own_message",
    "discord.add_reaction",
    "discord.create_thread",
    "discord.send_thread_message",
    "discord.send_attachment",
]


def register(ctx) -> None:
    ctx.register_connector(
        id="discord",
        name="Discord",
        category="Connectors",
        status_factory=lambda: {
            "id": "discord",
            "name": "Discord",
            "type": "connector",
            "category": "Connectors",
            "status": "backend_managed",
            "capabilities": list(CAPABILITIES),
        },
        service_factory=DiscordClient,
        capabilities=list(CAPABILITIES),
    )


__all__ = ["DiscordAccessPolicy", "DiscordClient", "auth", "client", "errors", "policy", "register"]
