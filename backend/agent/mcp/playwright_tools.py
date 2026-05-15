"""Playwright MCP browser automation wrapper.

The first Vellum browser-control layer is intentionally conservative:
navigation and snapshots are available by default, while actions that mutate
page state require PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true.
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

READ_ACTIONS = {
    "navigate": "browser_navigate",
    "snapshot": "browser_snapshot",
    "back": "browser_navigate_back",
    "forward": "browser_navigate_forward",
    "reload": "browser_reload",
    "close": "browser_close",
    "wait": "browser_wait_for",
}

MUTATING_ACTIONS = {
    "click": "browser_click",
    "type": "browser_type",
    "press_key": "browser_press_key",
    "select_option": "browser_select_option",
    "hover": "browser_hover",
}


def _server_params() -> StdioServerParameters:
    settings = get_settings()
    return StdioServerParameters(
        command=settings.playwright_mcp_command,
        args=shlex.split(settings.playwright_mcp_args),
        env=None,
    )


def _mutations_allowed() -> bool:
    return get_settings().playwright_mcp_allow_mutations


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
    return str(params.get("action") or "snapshot").strip().casefold().replace("-", "_")


def _tool_params(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action == "navigate":
        url = str(params.get("url") or params.get("query") or "").strip()
        if not url:
            raise ValueError("Playwright navigate requires a url.")
        return {"url": url}
    if action in {"snapshot", "back", "forward", "reload", "close"}:
        return {}
    if action == "wait":
        wait_params: dict[str, Any] = {}
        if params.get("time") is not None:
            wait_params["time"] = float(params["time"])
        if params.get("text"):
            wait_params["text"] = str(params["text"])
        return wait_params
    if action in {"click", "hover"}:
        return _element_ref_params(params)
    if action == "type":
        tool_params = _element_ref_params(params)
        text = str(params.get("text") or "")
        if not text:
            raise ValueError("Playwright type requires text.")
        tool_params["text"] = text
        if params.get("submit") is not None:
            tool_params["submit"] = bool(params["submit"])
        return tool_params
    if action == "press_key":
        key = str(params.get("key") or "").strip()
        if not key:
            raise ValueError("Playwright press_key requires key.")
        return {"key": key}
    if action == "select_option":
        tool_params = _element_ref_params(params)
        values = params.get("values", params.get("value"))
        if isinstance(values, str):
            tool_params["values"] = [values]
        elif isinstance(values, list):
            tool_params["values"] = [str(value) for value in values]
        else:
            raise ValueError("Playwright select_option requires value or values.")
        return tool_params
    raise ValueError(f"Unsupported Playwright action: {action}")


def _element_ref_params(params: dict[str, Any]) -> dict[str, Any]:
    ref = str(params.get("ref") or "").strip()
    if not ref:
        raise ValueError("Playwright action requires an accessibility ref from browser_snapshot.")
    tool_params = {"ref": ref}
    if params.get("element"):
        tool_params["element"] = str(params["element"])
    return tool_params


async def _run_tool_inner(params: dict[str, Any]) -> str:
    action = _action_name(params)
    tool_name = READ_ACTIONS.get(action) or MUTATING_ACTIONS.get(action)
    if tool_name is None:
        return f"Unsupported Playwright action: {action}."
    if action in MUTATING_ACTIONS and not _mutations_allowed():
        return f"Playwright action '{action}' requires PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true."

    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_names = _tool_names(await session.list_tools())
            if tool_name not in tool_names:
                return f"Playwright MCP server does not expose {tool_name}."
            result = await session.call_tool(tool_name, _tool_params(action, params))
            return _content_text(result) or f"Playwright {action} completed."


async def run_tool_async(params: dict[str, Any]) -> str:
    timeout = get_settings().mcp_timeout_seconds
    try:
        return await asyncio.wait_for(_run_tool_inner(params), timeout=timeout)
    except TimeoutError:
        return f"Playwright MCP timed out after {timeout} seconds."
    except Exception as exc:
        logger.error("[PLAYWRIGHT_MCP] Error: %s", exc)
        return f"Playwright MCP failed: {exc}"


def run_tool(params: dict[str, Any]) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_tool_async(params))
    raise RuntimeError("playwright_tools.run_tool cannot run inside an active event loop; use run_tool_async.")
