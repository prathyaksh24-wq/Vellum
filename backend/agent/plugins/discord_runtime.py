"""Vellum runtime adapter for the portable Discord bot connector."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from agent.config import REPO_ROOT, get_settings
from agent.plugins.portable import load_portable_plugin


PLUGIN_DIR = REPO_ROOT / "plugins" / "connectors" / "discord"


@lru_cache(maxsize=1)
def discord_plugin():
    return load_portable_plugin(PLUGIN_DIR)


_discord_module = discord_plugin().module
DiscordError = _discord_module.errors.DiscordError
DiscordAuthError = _discord_module.errors.DiscordAuthError
DiscordAPIError = _discord_module.errors.DiscordAPIError
DiscordPermissionError = _discord_module.errors.DiscordPermissionError


def discord_policy():
    settings = get_settings()
    return _discord_module.policy.DiscordAccessPolicy(
        allowed_guild_ids=_csv_ids(settings.discord_allowed_guild_ids),
        allowed_channel_ids=_csv_ids(settings.discord_allowed_channel_ids),
        autonomous_channel_ids=_csv_ids(settings.discord_autonomous_channel_ids),
    )


def discord_client(*, request_backend: Any | None = None):
    settings = get_settings()
    return _discord_module.client.DiscordClient(
        bot_token=settings.discord_bot_token,
        policy=discord_policy(),
        request_backend=request_backend,
    )


@lru_cache(maxsize=1)
def discord_service():
    from agent.tools.capabilities.discord_service import DiscordCapabilityService

    policy = discord_policy()
    return DiscordCapabilityService(
        allowed_guild_ids=policy.allowed_guild_ids,
        allowed_channel_ids=policy.allowed_channel_ids,
        autonomous_channel_ids=policy.autonomous_channel_ids,
    )


def discord_install_url() -> str:
    return _discord_module.auth.bot_install_url(application_id=get_settings().discord_application_id)


def discord_status(*, probe: bool = False) -> dict[str, Any]:
    settings = get_settings()
    configured = bool(settings.discord_application_id and settings.discord_bot_token)
    account: dict[str, Any] = {}
    status = "configured" if configured else "not_configured"
    if configured and probe:
        try:
            account = discord_client().get_current_user()
            status = "connected"
        except DiscordError:
            status = "unreachable"
    return {
        "configured": configured,
        "connected": status == "connected",
        "status": status,
        "application_id": settings.discord_application_id,
        "bot_id": str(account.get("id") or ""),
        "bot_username": str(account.get("global_name") or account.get("username") or ""),
        "allowed_guild_count": len(_csv_ids(settings.discord_allowed_guild_ids)),
        "allowed_channel_count": len(_csv_ids(settings.discord_allowed_channel_ids)),
        "autonomous_channel_count": len(_csv_ids(settings.discord_autonomous_channel_ids)),
    }


def portable_discord_status() -> dict[str, Any]:
    status = discord_status()
    return {
        "id": "discord",
        "name": "Discord",
        "type": "connector",
        "category": "Connectors",
        "configured": bool(status["configured"]),
        "status": str(status["status"]),
        "notes": "Installed bot access with explicit server and channel boundaries.",
        "capabilities": list(_discord_module.CAPABILITIES),
    }


def _csv_ids(value: str) -> frozenset[str]:
    return frozenset(item for raw in str(value or "").split(",") if (item := raw.strip()))
