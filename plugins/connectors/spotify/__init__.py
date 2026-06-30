"""Spotify portable plugin registration."""

from __future__ import annotations

from . import schemas, tools
from .auth import SpotifyAuthStore


TOOL_BINDINGS = (
    (schemas.SPOTIFY_PLAYBACK, tools.spotify_playback),
    (schemas.SPOTIFY_DEVICES, tools.spotify_devices),
    (schemas.SPOTIFY_QUEUE, tools.spotify_queue),
    (schemas.SPOTIFY_SEARCH, tools.spotify_search),
    (schemas.SPOTIFY_PLAYLISTS, tools.spotify_playlists),
    (schemas.SPOTIFY_ALBUMS, tools.spotify_albums),
    (schemas.SPOTIFY_LIBRARY, tools.spotify_library),
)


def spotify_status() -> dict:
    store = SpotifyAuthStore(tools.REPO_ROOT / "data" / "plugins" / "spotify")
    connected = store.auth_path.exists()
    return {
        "id": "spotify",
        "name": "Spotify",
        "type": "connector",
        "category": "Connectors",
        "configured": connected,
        "status": "ready" if connected else "not_configured",
        "notes": "Connected and ready for playback control." if connected else "Connect a Spotify account.",
        "capabilities": [schema["name"] for schema, _handler in TOOL_BINDINGS],
    }


def register(ctx) -> None:
    ctx.register_connector(
        id="spotify",
        name="Spotify",
        category="Connectors",
        status_factory=spotify_status,
        service_factory=tools.get_spotify_service,
        capabilities=[schema["name"] for schema, _handler in TOOL_BINDINGS],
    )
    for schema, handler in TOOL_BINDINGS:
        ctx.register_tool(
            name=schema["name"],
            toolset="spotify",
            schema=schema,
            handler=handler,
        )
