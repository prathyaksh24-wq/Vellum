"""Vellum runtime adapter for the portable Spotify plugin."""

from __future__ import annotations

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


def spotify_is_authenticated() -> bool:
    from plugins.connectors.spotify.auth import SpotifyAuthStore

    try:
        saved = SpotifyAuthStore(AUTH_DIR).load_tokens()
    except Exception:
        return False
    return bool(saved.get("access_token") and saved.get("refresh_token") and saved.get("client_id"))


def registered_spotify_context() -> PortablePluginContext:
    context = PortablePluginContext()
    load_portable_plugin(PLUGIN_DIR).register(context)
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
