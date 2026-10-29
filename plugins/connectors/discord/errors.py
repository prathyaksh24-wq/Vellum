"""Sanitized Discord connector failures."""


class DiscordError(RuntimeError):
    code = "discord_error"


class DiscordAuthError(DiscordError):
    code = "discord_auth_error"


class DiscordAPIError(DiscordError):
    code = "discord_api_error"


class DiscordPermissionError(DiscordError):
    code = "discord_permission_error"
