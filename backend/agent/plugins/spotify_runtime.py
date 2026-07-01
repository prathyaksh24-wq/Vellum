"""Vellum runtime adapter for the portable Spotify plugin."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

from langchain_core.tools import StructuredTool

from agent.plugins.portable import (
    PortablePluginContext,
    PortableRegisteredTool,
    load_portable_plugin,
)
from agent.privacy.classifier import RED_PATTERNS


REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "plugins" / "connectors" / "spotify"
AUTH_DIR = REPO_ROOT / "data" / "plugins" / "spotify"


@lru_cache(maxsize=1)
def spotify_plugin():
    return load_portable_plugin(PLUGIN_DIR)


_spotify_module = spotify_plugin().module
SpotifyAuthError = _spotify_module.auth.SpotifyAuthError
SpotifyError = _spotify_module.tools.SpotifyError
SpotifyRateLimited = _spotify_module.tools.SpotifyRateLimited


def spotify_store():
    return _spotify_module.auth.SpotifyAuthStore(AUTH_DIR)


def spotify_client():
    return _spotify_module.tools.get_spotify_service()


def spotify_pkce_pair():
    return _spotify_module.auth.new_pkce_pair()


def spotify_authorization_url(**kwargs):
    return _spotify_module.auth.authorization_url(**kwargs)


def portable_spotify_status() -> dict:
    return _spotify_module.spotify_status()


def spotify_playback(args: dict, **kwargs) -> str:
    return _spotify_module.tools.spotify_playback(args, **kwargs)


def spotify_devices(args: dict, **kwargs) -> str:
    return _spotify_module.tools.spotify_devices(args, **kwargs)


def spotify_is_authenticated() -> bool:

    try:
        saved = spotify_store().load_tokens()
    except Exception:
        return False
    return bool(saved.get("access_token") and saved.get("refresh_token") and saved.get("client_id"))


def registered_spotify_context() -> PortablePluginContext:
    context = PortablePluginContext()
    spotify_plugin().register(context)
    return context


def spotify_catalog_query_gate(query: str) -> tuple[str | None, str | None]:
    for pattern, _reason in RED_PATTERNS:
        if pattern.search(query):
            return None, "Withheld."
    explicit_identifiers = (
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
        re.compile(r"(?<!\d)(?:\+?\d[\d .()-]{7,}\d)(?!\d)"),
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    )
    if any(pattern.search(query) for pattern in explicit_identifiers):
        return None, "Withheld."
    return query, None


def as_langchain_tool(record: PortableRegisteredTool) -> StructuredTool:
    def invoke(**kwargs):
        return record.handler(kwargs, privacy_gate=spotify_catalog_query_gate)

    return StructuredTool.from_function(
        func=invoke,
        name=record.name,
        description=str(record.schema["description"]),
        args_schema=dict(record.schema["parameters"]),
    )


def portable_agent_tools() -> list[StructuredTool]:
    if not spotify_is_authenticated():
        return []
    context = registered_spotify_context()
    return [as_langchain_tool(context.tools[name]) for name in sorted(context.tools)]
