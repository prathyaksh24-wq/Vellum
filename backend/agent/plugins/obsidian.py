"""Status for the optional Obsidian connector (the user's own vault)."""

from __future__ import annotations

from typing import Any

from agent.config import get_settings


def obsidian_plugin_status() -> dict[str, Any]:
    settings = get_settings()
    configured = bool(settings.obsidian_api_key)
    permissions = []
    if settings.obsidian_mcp_allow_writes:
        permissions.append("writes")
    if settings.obsidian_mcp_allow_destructive:
        permissions.append("deletes")
    if settings.obsidian_mcp_allow_commands:
        permissions.append("commands")
    allowed = ", ".join(permissions) if permissions else "read-only"
    return {
        "id": "obsidian",
        "configured": configured,
        "status": "ready" if configured else "needs_setup",
        "notes": (
            f"Connects through the Obsidian Local REST API at {settings.obsidian_mcp_url} ({allowed})."
            if configured
            else "Set OBSIDIAN_API_KEY from Obsidian's Local REST API plugin to connect your vault."
        ),
        "metadata": {
            "provider": "Obsidian",
            "integration": "Obsidian Local REST API · optional user vault",
            "website": "https://obsidian.md",
            "access": allowed,
        },
    }
