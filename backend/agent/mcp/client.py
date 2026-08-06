"""Concurrent MCP tool runner."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from agent.config import get_settings
from agent.mcp.results import UNREACHABLE, looks_unreachable, normalize_mcp_text
from agent.mcp import (
    apify_tools,
    context7_tools,
    context_mode_tools,
    firecrawl_tools,
    github_tools,
    gitmcp_tools,
    obsidian_tools,
    playwright_tools,
    tavily_tools,
)


logger = logging.getLogger(__name__)

ToolFn = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class McpToolRequest:
    server: str
    params: dict[str, Any]


@dataclass(frozen=True)
class McpToolResult:
    server: str
    ok: bool
    result: str


SERVER_RUNNERS: dict[str, ToolFn] = {
    "apify_amazon": apify_tools.run_tool_async,
    "apify": apify_tools.run_tool_async,
    "github": github_tools.run_tool_async,
    "obsidian": obsidian_tools.run_tool_async,
    "obsidian_api": obsidian_tools.run_tool_async,
    "context7": context7_tools.run_tool_async,
    "library_docs": context7_tools.run_tool_async,
    "gitmcp": gitmcp_tools.run_tool_async,
    "repo_docs": gitmcp_tools.run_tool_async,
    "context_mode": context_mode_tools.run_tool_async,
    "ctx": context_mode_tools.run_tool_async,
    "playwright": playwright_tools.run_tool_async,
    "browser": playwright_tools.run_tool_async,
    "tavily": tavily_tools.run_tool_async,
    "web_research": tavily_tools.run_tool_async,
    "firecrawl": firecrawl_tools.run_tool_async,
    "web_extract": firecrawl_tools.run_tool_async,
}


async def _run_one(request: McpToolRequest) -> McpToolResult:
    runner = SERVER_RUNNERS.get(request.server)
    if runner is None:
        logger.warning("Unknown MCP server: %s", request.server)
        return McpToolResult(request.server, False, UNREACHABLE)

    timeout = get_settings().mcp_timeout_seconds
    try:
        raw_result = await asyncio.wait_for(runner(request.params), timeout=timeout)
        if looks_unreachable(raw_result):
            return McpToolResult(request.server, False, UNREACHABLE)
        return McpToolResult(request.server, True, normalize_mcp_text(raw_result))
    except Exception as exc:
        logger.warning("MCP server %s is unreachable: %s", request.server, exc)
        return McpToolResult(request.server, False, UNREACHABLE)


async def run_tools_async(requests: list[McpToolRequest | dict[str, Any]]) -> list[McpToolResult]:
    normalized = [
        request
        if isinstance(request, McpToolRequest)
        else McpToolRequest(
            server=str(request.get("server") or request.get("tool_name") or request.get("name") or ""),
            params=dict(request.get("params") or request.get("tool_params") or {}),
        )
        for request in requests
    ]
    return await asyncio.gather(*(_run_one(request) for request in normalized))


def run_tools(requests: list[McpToolRequest | dict[str, Any]]) -> list[McpToolResult]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_tools_async(requests))
    raise RuntimeError("run_tools cannot run inside an active event loop; use run_tools_async.")

