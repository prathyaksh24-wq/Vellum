"""Discord bot installation URL helpers."""

from __future__ import annotations

from urllib.parse import urlencode

from .errors import DiscordAuthError


AUTHORIZATION_URL = "https://discord.com/oauth2/authorize"
VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
ADD_REACTIONS = 1 << 6
EMBED_LINKS = 1 << 14
ATTACH_FILES = 1 << 15
READ_MESSAGE_HISTORY = 1 << 16
USE_EXTERNAL_EMOJIS = 1 << 18
CREATE_PUBLIC_THREADS = 1 << 35
SEND_MESSAGES_IN_THREADS = 1 << 38
DEFAULT_BOT_PERMISSIONS = (
    ADD_REACTIONS
    | VIEW_CHANNEL
    | SEND_MESSAGES
    | EMBED_LINKS
    | ATTACH_FILES
    | READ_MESSAGE_HISTORY
    | USE_EXTERNAL_EMOJIS
    | CREATE_PUBLIC_THREADS
    | SEND_MESSAGES_IN_THREADS
)
GUILD_INSTALL_TYPE = 0


def bot_install_url(*, application_id: str, permissions: int = DEFAULT_BOT_PERMISSIONS) -> str:
    clean = str(application_id or "").strip()
    if not clean or not clean.isdigit():
        raise DiscordAuthError("Discord application ID is not configured")
    query = urlencode(
        {
            "client_id": clean,
            "scope": "bot",
            "permissions": permissions,
            "integration_type": GUILD_INSTALL_TYPE,
        }
    )
    return f"{AUTHORIZATION_URL}?{query}"
