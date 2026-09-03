"""Discord bot installation URL helpers."""

from __future__ import annotations

from urllib.parse import urlencode

from .errors import DiscordAuthError


AUTHORIZATION_URL = "https://discord.com/oauth2/authorize"
VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
READ_MESSAGE_HISTORY = 1 << 16
DEFAULT_BOT_PERMISSIONS = VIEW_CHANNEL | SEND_MESSAGES | READ_MESSAGE_HISTORY


def bot_install_url(*, application_id: str, permissions: int = DEFAULT_BOT_PERMISSIONS) -> str:
    clean = str(application_id or "").strip()
    if not clean or not clean.isdigit():
        raise DiscordAuthError("Discord application ID is not configured")
    query = urlencode(
        {
            "client_id": clean,
            "scope": "bot",
            "permissions": permissions,
        }
    )
    return f"{AUTHORIZATION_URL}?{query}"
