"""Tavily remote MCP wrapper for shared web research.

Tavily is used as a source-backed research/search provider. The remote MCP
endpoint accepts the API key as a query parameter, so the configured base URL is
kept keyless and the key is appended only at call time.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from agent.config import get_settings

logger = logging.getLogger(__name__)

ACTION_TO_TOOL = {
    "search": "tavily_search",
    "tavily_search": "tavily_search",
    "answer": "tavily_search",
}


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


def _server_url() -> str:
    settings = get_settings()
    api_key = settings.tavily_api_key
    if not api_key:
        raise ValueError("TAVILY_API_KEY is not configured.")
    parsed = urllib.parse.urlparse(settings.tavily_mcp_url)
    query = urllib.parse.parse_qs(parsed.query)
    query["tavilyApiKey"] = [api_key]
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))


def _tool_params(action: str, params: dict[str, Any]) -> dict[str, Any]:
    query = str(params.get("query") or params.get("q") or "").strip()
    if not query:
        raise ValueError("Tavily search requires query.")
    out: dict[str, Any] = {"query": query}
    if action == "answer":
        out["include_answer"] = True
    for key in ("search_depth", "topic", "include_domains", "exclude_domains", "max_results"):
        if params.get(key) not in (None, ""):
            out[key] = params[key]
    return out


async def _run_tool_inner(params: dict[str, Any]) -> str:
    action = _action_name(params)
    tool_name = ACTION_TO_TOOL.get(action)
    if tool_name is None:
        return f"Unsupported Tavily action: {action or 'missing'}."
    try:
        call_params = _tool_params(action, params)
    except ValueError as exc:
        return str(exc)

    settings = get_settings()
    timeout = settings.mcp_timeout_seconds
    async with streamablehttp_client(
        _server_url(),
        timeout=timeout,
        sse_read_timeout=timeout,
    ) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_names = _tool_names(await session.list_tools())
            if tool_name not in tool_names:
                return f"Tavily MCP server does not expose {tool_name}."
            result = await session.call_tool(tool_name, call_params)
            return _content_text(result) or f"Tavily {action} completed."


async def run_tool_async(params: dict[str, Any]) -> str:
    timeout = get_settings().mcp_timeout_seconds
    try:
        return await asyncio.wait_for(_run_tool_inner(params), timeout=timeout)
    except TimeoutError:
        return f"Tavily MCP timed out after {timeout} seconds."
    except Exception as exc:
        logger.error("[TAVILY_MCP] Error: %s", exc)
        return f"Tavily MCP failed: {exc}"


def run_tool(params: dict[str, Any]) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_tool_async(params))
    raise RuntimeError("tavily_tools.run_tool cannot run inside an active event loop; use run_tool_async.")
