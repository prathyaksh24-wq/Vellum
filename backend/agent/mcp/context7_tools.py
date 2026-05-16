"""Context7 MCP wrapper for up-to-date library documentation lookup.

Context7 is a read-only documentation service. Two tools are exposed:

- ``resolve-library-id`` — turn a free-form library name into the Context7
  library identifier the docs lookup expects.
- ``query-docs`` — fetch focused, current documentation for a resolved
  library, optionally narrowed by topic and capped by token count.

The hosted endpoint works without an API key (rate-limited); when
``CONTEXT7_API_KEY`` is set, it is sent as a bearer token for higher limits.
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
    "resolve": "resolve-library-id",
    "resolve_library_id": "resolve-library-id",
    "resolve-library-id": "resolve-library-id",
    "docs": "query-docs",
    "query_docs": "query-docs",
    "query-docs": "query-docs",
    "get_library_docs": "query-docs",
    "get-library-docs": "query-docs",
}


def _context7_api_key() -> str:
    return get_settings().context7_api_key


def _context7_headers() -> dict[str, str]:
    key = _context7_api_key()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


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
    return str(params.get("action") or params.get("tool") or "").strip().casefold().replace(" ", "_")


def _tool_params(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "resolve-library-id":
        library = str(params.get("library") or params.get("libraryName") or params.get("query") or "").strip()
        if not library:
            raise ValueError("Context7 resolve requires a library name.")
        query = str(params.get("query") or params.get("task") or f"Find documentation for {library}.").strip()
        return {"libraryName": library, "query": query}

    library_id = str(
        params.get("library_id")
        or params.get("libraryId")
        or params.get("context7CompatibleLibraryID")
        or ""
    ).strip()
    if not library_id:
        raise ValueError("Context7 docs requires a library_id from resolve-library-id.")
    query = str(params.get("query") or params.get("topic") or "Get the relevant documentation.").strip()
    tool_params: dict[str, Any] = {"libraryId": library_id, "query": query}
    return tool_params


async def _run_tool_inner(params: dict[str, Any]) -> str:
    action = _action_name(params)
    tool_name = ACTION_TO_TOOL.get(action)
    if tool_name is None:
        return f"Unsupported Context7 action: {action or 'missing'}."

    try:
        call_params = _tool_params(tool_name, params)
    except ValueError as exc:
        return str(exc)

    settings = get_settings()
    timeout = settings.mcp_timeout_seconds
    async with streamablehttp_client(
        settings.context7_mcp_url,
        headers=_context7_headers(),
        timeout=timeout,
        sse_read_timeout=timeout,
    ) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_names = _tool_names(await session.list_tools())
            if tool_name not in tool_names:
                return f"Context7 MCP server does not expose {tool_name}."
            result = await session.call_tool(tool_name, call_params)
            return _content_text(result) or f"Context7 {action} completed."


async def run_tool_async(params: dict[str, Any]) -> str:
    timeout = get_settings().mcp_timeout_seconds
    try:
        return await asyncio.wait_for(_run_tool_inner(params), timeout=timeout)
    except TimeoutError:
        return f"Context7 MCP timed out after {timeout} seconds."
    except Exception as exc:
        logger.error("[CONTEXT7_MCP] Error: %s", exc)
        return f"Context7 MCP failed: {exc}"


def run_tool(params: dict[str, Any]) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_tool_async(params))
    raise RuntimeError("context7_tools.run_tool cannot run inside an active event loop; use run_tool_async.")
