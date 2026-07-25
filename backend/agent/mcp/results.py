"""Normalize MCP results before they enter the agent context."""

from __future__ import annotations

import re

UNREACHABLE = "Unreachable."
MAX_MCP_RESULT_CHARS = 12_000
_FAILURE_PREFIXES = (
    "apify search failed:",
    "apify search timed out after ",
    "context7 mcp failed:",
    "context7 mcp timed out after ",
    "context mode failed:",
    "context mode timed out after ",
    "filesystem mcp failed:",
    "filesystem mcp timed out after ",
    "firecrawl mcp failed:",
    "firecrawl mcp timed out after ",
    "github mcp failed:",
    "github mcp timed out after ",
    "gitmcp failed:",
    "gitmcp timed out after ",
    "obsidian mcp failed:",
    "obsidian mcp timed out after ",
    "playwright mcp failed:",
    "playwright mcp timed out after ",
    "tavily mcp failed:",
    "tavily mcp timed out after ",
)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def looks_unreachable(value: object) -> bool:
    """Recognize legacy adapter failures without exposing their details."""

    text = str(value or "").strip()
    lowered = text.casefold()
    return text == UNREACHABLE or any(lowered.startswith(prefix) for prefix in _FAILURE_PREFIXES)


def normalize_mcp_text(value: object, *, max_chars: int = MAX_MCP_RESULT_CHARS) -> str:
    """Return a bounded, display-safe projection of an MCP result.

    The projection preserves source text for accurate retrieval while removing
    control characters and preventing one tool call from consuming unbounded
    model context.
    """

    if looks_unreachable(value):
        return UNREACHABLE

    text = _CONTROL_CHARS.sub("", str(value or "")).replace("\r\n", "\n").strip()
    if len(text) <= max_chars:
        return text

    boundary = text.rfind("\n", 0, max_chars)
    if boundary < max_chars // 2:
        boundary = max_chars
    return text[:boundary].rstrip() + "\n\n[MCP result truncated locally]"