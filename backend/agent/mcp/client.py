"""Concurrent MCP tool runner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from agent.config import get_settings
from agent.mcp import (
    apify_tools,
    context7_tools,
    context_mode_tools,
    firecrawl_tools,
    filesystem_tools,
    github_tools,
    gitmcp_tools,
    obsidian_tools,
    playwright_tools,
    tavily_tools,
)


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
    "filesystem": filesystem_tools.run_tool_async,
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
        return McpToolResult(request.server, False, f"Unknown MCP server: {request.server}")

    timeout = get_settings().mcp_timeout_seconds
    try:
        result = await asyncio.wait_for(runner(request.params), timeout=timeout)
        return McpToolResult(request.server, True, result)
    except TimeoutError:
        return McpToolResult(request.server, False, f"{request.server} timed out after {timeout} seconds.")
    except Exception as exc:
        return McpToolResult(request.server, False, f"{request.server} failed: {exc}")


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

