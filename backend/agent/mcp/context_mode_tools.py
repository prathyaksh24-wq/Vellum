"""Context Mode (mksglu/context-mode) MCP wrapper.

Context Mode is a stdio MCP server that sandboxes tool output to keep raw
data out of the LLM context window. It exposes:

- Sandboxed code execution in 12 languages (``ctx_execute``)
- Markdown chunking + FTS5/BM25 indexing (``ctx_index``)
- Indexed-content search (``ctx_search``)
- Fetch-and-index for URLs with a 24h cache (``ctx_fetch_and_index``)
- Operational helpers: ``ctx_stats``, ``ctx_doctor``, ``ctx_purge``

The batch/file execute variants and the admin-only ``ctx_upgrade`` and
``ctx_insight`` tools are intentionally not surfaced — they target IDE
coding-agent workflows that don't apply inside Vellum's LangGraph loop.
"""

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
    "execute": "ctx_execute",
    "ctx_execute": "ctx_execute",
    "run": "ctx_execute",
    "index": "ctx_index",
    "ctx_index": "ctx_index",
    "search": "ctx_search",
    "ctx_search": "ctx_search",
    "fetch_and_index": "ctx_fetch_and_index",
    "ctx_fetch_and_index": "ctx_fetch_and_index",
    "fetch": "ctx_fetch_and_index",
    "stats": "ctx_stats",
    "ctx_stats": "ctx_stats",
    "doctor": "ctx_doctor",
    "ctx_doctor": "ctx_doctor",
    "purge": "ctx_purge",
    "ctx_purge": "ctx_purge",
}

DESTRUCTIVE_ACTIONS = {"ctx_purge"}


def _server_params() -> StdioServerParameters:
    settings = get_settings()
    return StdioServerParameters(
        command=settings.context_mode_mcp_command,
        args=shlex.split(settings.context_mode_mcp_args) if settings.context_mode_mcp_args else [],
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


def _action_name(params: dict[str, Any]) -> str:
    return str(params.get("action") or params.get("tool") or "").strip().casefold().replace("-", "_")


def _tool_params(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "ctx_execute":
        language = str(params.get("language") or params.get("lang") or "").strip()
        code = str(params.get("code") or "")
        if not language:
            raise ValueError("ctx_execute requires language (e.g. python, javascript, bash).")
        if not code:
            raise ValueError("ctx_execute requires code.")
        out: dict[str, Any] = {"language": language, "code": code}
        if params.get("timeout") not in (None, "", 0):
            try:
                out["timeout"] = int(params["timeout"])
            except (TypeError, ValueError):
                pass
        return out

    if tool_name == "ctx_index":
        content = str(params.get("content") or "")
        if not content:
            raise ValueError("ctx_index requires content.")
        out = {"content": content}
        if params.get("source"):
            out["source"] = str(params["source"])
        if params.get("title"):
            out["title"] = str(params["title"])
        return out

    if tool_name == "ctx_search":
        query = params.get("query")
        if isinstance(query, str):
            queries = [query.strip()] if query.strip() else []
        elif isinstance(query, list):
            queries = [str(item).strip() for item in query if str(item).strip()]
        else:
            queries = []
        if not queries:
            raise ValueError("ctx_search requires query (string or list).")
        out: dict[str, Any] = {"queries": queries}
        if params.get("content_type"):
            out["contentType"] = str(params["content_type"])
        if params.get("source"):
            out["source"] = str(params["source"])
        return out

    if tool_name == "ctx_fetch_and_index":
        url = str(params.get("url") or "").strip()
        if not url:
            raise ValueError("ctx_fetch_and_index requires url.")
        if not url.startswith(("http://", "https://")):
            raise ValueError("ctx_fetch_and_index only accepts http(s) URLs.")
        out: dict[str, Any] = {"requests": [{"url": url, "source": params.get("source") or url}]}
        if params.get("force"):
            out["force"] = True
        return out

    return {}


async def _run_tool_inner(params: dict[str, Any]) -> str:
    action = _action_name(params)
    tool_name = ACTION_TO_TOOL.get(action)
    if tool_name is None:
        return f"Unsupported Context Mode action: {action or 'missing'}."

    try:
        call_params = _tool_params(tool_name, params)
    except ValueError as exc:
        return str(exc)

    if tool_name in DESTRUCTIVE_ACTIONS and not params.get("confirm"):
        return f"Context Mode action '{action}' requires confirm=true."

    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_names = _tool_names(await session.list_tools())
            if tool_name not in tool_names:
                return f"Context Mode server does not expose {tool_name}."
            result = await session.call_tool(tool_name, call_params)
            return _content_text(result) or f"Context Mode {action} completed."


async def run_tool_async(params: dict[str, Any]) -> str:
    timeout = get_settings().mcp_timeout_seconds
    try:
        return await asyncio.wait_for(_run_tool_inner(params), timeout=timeout)
    except TimeoutError:
        return f"Context Mode timed out after {timeout} seconds."
    except Exception as exc:
        logger.error("[CONTEXT_MODE] Error: %s", exc)
        return f"Context Mode failed: {exc}"


def run_tool(params: dict[str, Any]) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_tool_async(params))
    raise RuntimeError("context_mode_tools.run_tool cannot run inside an active event loop; use run_tool_async.")
