"""
Filesystem MCP tool wrapper.

The official filesystem MCP server is launched with the Obsidian vault as its
only allowed root. Any explicit path is resolved and checked locally before the
MCP call is made.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import re
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent.config import get_settings

logger = logging.getLogger(__name__)


PATH_PATTERN = re.compile(r"(?P<path>(?:[\w .-]+/)+[\w .-]+(?:\.md|\.txt|\.pdf)?|[\w .-]+\.(?:md|txt|pdf))")


def _server_params() -> StdioServerParameters:
    settings = get_settings()
    return StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", str(settings.obsidian_vault_path)],
        env=None,
    )


def _content_text(result: Any) -> str:
    content = getattr(result, "content", None) or []
    parts = []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(str(text))
    return "\n".join(parts).strip()


def _tool_names(tools_result: Any) -> set[str]:
    return {tool.name for tool in getattr(tools_result, "tools", [])}


def _extract_path(query: str) -> Path | None:
    match = PATH_PATTERN.search(query or "")
    if not match:
        return None
    return Path(match.group("path").strip())


def _resolve_vault_path(path: Path) -> Path:
    settings = get_settings()
    vault = settings.obsidian_vault_path.resolve()
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = vault / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(vault):
        raise ValueError("Filesystem MCP path must stay inside the Obsidian vault.")
    return candidate


async def _run_tool_inner(params: dict) -> str:
    query = params.get("query", "")
    requested_path = _extract_path(query)
    settings = get_settings()

    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_names = _tool_names(await session.list_tools())

            if requested_path is not None:
                target = _resolve_vault_path(requested_path)
                if "read_file" in tool_names:
                    result = await session.call_tool("read_file", {"path": str(target)})
                    return _content_text(result) or "File not found."
                return "Filesystem MCP server does not expose read_file."

            if "list_directory" in tool_names:
                result = await session.call_tool(
                    "list_directory",
                    {"path": str(settings.obsidian_vault_path)},
                )
                return _content_text(result) or "No files found."

    return "Filesystem tool: no matching operation."


async def run_tool_async(params: dict) -> str:
    timeout = get_settings().mcp_timeout_seconds
    try:
        return await asyncio.wait_for(_run_tool_inner(params), timeout=timeout)
    except TimeoutError:
        return f"Filesystem MCP timed out after {timeout} seconds."


def run_tool(params: dict) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_tool_async(params))
    raise RuntimeError("filesystem_tools.run_tool cannot run inside an active event loop; use run_tool_async.")
