"""GitMCP (gitmcp.io / idosal/git-mcp) wrapper.

GitMCP turns any GitHub repository's documentation and code into MCP tools.
Vellum uses the dynamic ``/docs`` endpoint, which exposes generic tools that
take owner/repo as parameters rather than baking a specific repo into the
URL.

The hosted service is open and read-only — no API key required.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from agent.config import get_settings

logger = logging.getLogger(__name__)

ACTION_TO_TOOL = {
    "match": "match_common_libs_owner_repo_mapping",
    "match_library": "match_common_libs_owner_repo_mapping",
    "match_common_libs_owner_repo_mapping": "match_common_libs_owner_repo_mapping",
    "fetch_docs": "fetch_generic_documentation",
    "fetch_documentation": "fetch_generic_documentation",
    "fetch_generic_documentation": "fetch_generic_documentation",
    "search_docs": "search_generic_documentation",
    "search_documentation": "search_generic_documentation",
    "search_generic_documentation": "search_generic_documentation",
    "search_code": "search_generic_code",
    "search_generic_code": "search_generic_code",
    "fetch_url": "fetch_generic_url_content",
    "fetch_generic_url_content": "fetch_generic_url_content",
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


def _tool_params(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "match_common_libs_owner_repo_mapping":
        library = str(params.get("library") or params.get("libraryName") or params.get("query") or "").strip()
        if not library:
            raise ValueError("GitMCP match requires a library name.")
        return {"library": library}

    if tool_name == "fetch_generic_url_content":
        url = str(params.get("url") or "").strip()
        if not url:
            raise ValueError("GitMCP fetch_url requires a url.")
        return {"url": url}

    owner = str(params.get("owner") or "").strip()
    repo = str(params.get("repo") or "").strip()
    if not owner or not repo:
        raise ValueError("GitMCP requires owner and repo.")
    tool_params: dict[str, Any] = {"owner": owner, "repo": repo}

    if tool_name in {"search_generic_documentation", "search_generic_code"}:
        query = str(params.get("query") or "").strip()
        if not query:
            raise ValueError("GitMCP search requires a query.")
        tool_params["query"] = query
        page = params.get("page")
        if tool_name == "search_generic_code" and page not in (None, "", 0):
            try:
                tool_params["page"] = int(page)
            except (TypeError, ValueError):
                pass

    return tool_params


async def _run_tool_inner(params: dict[str, Any]) -> str:
    action = _action_name(params)
    tool_name = ACTION_TO_TOOL.get(action)
    if tool_name is None:
        return f"Unsupported GitMCP action: {action or 'missing'}."

    try:
        call_params = _tool_params(tool_name, params)
    except ValueError as exc:
        return str(exc)

    settings = get_settings()
    timeout = settings.mcp_timeout_seconds
    async with streamablehttp_client(
        settings.gitmcp_mcp_url,
        timeout=timeout,
        sse_read_timeout=timeout,
    ) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_names = _tool_names(await session.list_tools())
            if tool_name not in tool_names:
                return f"GitMCP server does not expose {tool_name}."
            result = await session.call_tool(tool_name, call_params)
            return _content_text(result) or f"GitMCP {action} completed."


async def run_tool_async(params: dict[str, Any]) -> str:
    timeout = get_settings().mcp_timeout_seconds
    try:
        return await asyncio.wait_for(_run_tool_inner(params), timeout=timeout)
    except TimeoutError:
        return f"GitMCP timed out after {timeout} seconds."
    except Exception as exc:
        logger.error("[GITMCP] Error: %s", exc)
        return f"GitMCP failed: {exc}"


def run_tool(params: dict[str, Any]) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_tool_async(params))
    raise RuntimeError("gitmcp_tools.run_tool cannot run inside an active event loop; use run_tool_async.")
