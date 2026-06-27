"""Firecrawl MCP wrapper for page fetch, crawl, and extraction."""

from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent.config import get_settings

logger = logging.getLogger(__name__)

ACTION_TO_TOOL = {
    "fetch": "firecrawl_scrape",
    "scrape": "firecrawl_scrape",
    "firecrawl_scrape": "firecrawl_scrape",
    "crawl": "firecrawl_crawl",
    "firecrawl_crawl": "firecrawl_crawl",
    "extract": "firecrawl_extract",
    "firecrawl_extract": "firecrawl_extract",
}


def _server_params() -> StdioServerParameters:
    settings = get_settings()
    if not settings.firecrawl_api_key:
        raise ValueError("FIRECRAWL_API_KEY is not configured.")
    return StdioServerParameters(
        command=settings.firecrawl_mcp_command,
        args=shlex.split(settings.firecrawl_mcp_args) if settings.firecrawl_mcp_args else [],
        env={"FIRECRAWL_API_KEY": settings.firecrawl_api_key},
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


def _action_name(params: dict[str, Any]) -> str:
    return str(params.get("action") or params.get("tool") or "").strip().casefold().replace("-", "_")


def _url(params: dict[str, Any]) -> str:
    url = str(params.get("url") or "").strip()
    if not url:
        raise ValueError("Firecrawl action requires url.")
    if not url.startswith(("http://", "https://")):
        raise ValueError("Firecrawl only accepts http(s) URLs.")
    return url


def _tool_params(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "firecrawl_scrape":
        out: dict[str, Any] = {"url": _url(params), "formats": params.get("formats") or ["markdown"]}
    elif tool_name == "firecrawl_crawl":
        out = {"url": _url(params)}
        if params.get("limit") not in (None, ""):
            out["limit"] = params["limit"]
    elif tool_name == "firecrawl_extract":
        out = {"url": _url(params)}
        if params.get("schema") not in (None, ""):
            out["schema"] = params["schema"]
        if params.get("prompt") not in (None, ""):
            out["prompt"] = params["prompt"]
    else:
        out = {}

    for key in ("onlyMainContent", "waitFor", "timeout", "includePaths", "excludePaths"):
        if params.get(key) not in (None, ""):
            out[key] = params[key]
    return out


async def _run_tool_inner(params: dict[str, Any]) -> str:
    action = _action_name(params)
    tool_name = ACTION_TO_TOOL.get(action)
    if tool_name is None:
        return f"Unsupported Firecrawl action: {action or 'missing'}."
    try:
        call_params = _tool_params(tool_name, params)
    except ValueError as exc:
        return str(exc)

    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_names = _tool_names(await session.list_tools())
            if tool_name not in tool_names:
                return f"Firecrawl MCP server does not expose {tool_name}."
            result = await session.call_tool(tool_name, call_params)
            return _content_text(result) or f"Firecrawl {action} completed."


async def run_tool_async(params: dict[str, Any]) -> str:
    timeout = get_settings().mcp_timeout_seconds
    try:
        return await asyncio.wait_for(_run_tool_inner(params), timeout=timeout)
    except TimeoutError:
        return f"Firecrawl MCP timed out after {timeout} seconds."
    except Exception as exc:
        logger.error("[FIRECRAWL_MCP] Error: %s", exc)
        return f"Firecrawl MCP failed: {exc}"


def run_tool(params: dict[str, Any]) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_tool_async(params))
    raise RuntimeError("firecrawl_tools.run_tool cannot run inside an active event loop; use run_tool_async.")
