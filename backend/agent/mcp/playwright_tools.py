"""Playwright MCP browser automation wrapper.

The first Vellum browser-control layer is intentionally conservative:
navigation and snapshots are available by default, while actions that mutate
page state require PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import shlex
import threading
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
    "screenshot": "browser_take_screenshot",
    "take_screenshot": "browser_take_screenshot",
    "resize": "browser_resize",
    "console": "browser_console_messages",
    "console_messages": "browser_console_messages",
    "network": "browser_network_requests",
    "network_requests": "browser_network_requests",
    "tabs": "browser_tabs",
    "tab": "browser_tabs",
    "new_tab": "browser_tabs",
    "select_tab": "browser_tabs",
    "close_tab": "browser_tabs",
    "list_tabs": "browser_tabs",
}

MUTATING_ACTIONS = {
    "click": "browser_click",
    "type": "browser_type",
    "press_key": "browser_press_key",
    "select_option": "browser_select_option",
    "hover": "browser_hover",
    "drag": "browser_drag",
    "fill_form": "browser_fill_form",
    "evaluate": "browser_evaluate",
}

CLOSE_ACTIONS = {"close", "close_tab"}


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


def _mcp_action_timeout_seconds(action: str) -> float:
    timeout = float(get_settings().mcp_timeout_seconds)
    if action in CLOSE_ACTIONS:
        return min(timeout, 10.0)
    return timeout


def _tool_params(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action == "navigate":
        url = str(params.get("url") or params.get("query") or "").strip()
        if not url:
            raise ValueError("Playwright navigate requires a url.")
        return {"url": url}
    if action in {"snapshot", "back", "forward", "reload", "close"}:
        return {}
    if action in {"screenshot", "take_screenshot"}:
        return _screenshot_params(params)
    if action == "resize":
        return {
            "width": int(params.get("width") or 0),
            "height": int(params.get("height") or 0),
        }
    if action in {"console", "console_messages"}:
        return {
            "level": str(params.get("level") or "info"),
            **({"all": bool(params["all"])} if params.get("all") is not None else {}),
            **({"filename": str(params["filename"])} if params.get("filename") else {}),
        }
    if action in {"network", "network_requests"}:
        network_params: dict[str, Any] = {"static": bool(params.get("static", False))}
        if params.get("filter"):
            network_params["filter"] = str(params["filter"])
        if params.get("filename"):
            network_params["filename"] = str(params["filename"])
        return network_params
    if action == "wait":
        wait_params: dict[str, Any] = {}
        if params.get("time") is not None:
            wait_params["time"] = float(params["time"])
        if params.get("text"):
            wait_params["text"] = str(params["text"])
        return wait_params
    if action in {"tabs", "tab", "new_tab", "select_tab", "close_tab", "list_tabs"}:
        return _tab_params(action, params)
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
    if action == "drag":
        return _drag_params(params)
    if action == "fill_form":
        fields = params.get("fields")
        if fields is None and params.get("fields_json"):
            fields = json.loads(str(params["fields_json"]))
        if not isinstance(fields, list) or not fields:
            raise ValueError("Playwright fill_form requires fields.")
        return {"fields": fields}
    if action == "evaluate":
        function = str(params.get("function") or params.get("script") or "").strip()
        if not function:
            raise ValueError("Playwright evaluate requires function.")
        eval_params: dict[str, Any] = {"function": function}
        target = str(params.get("target") or params.get("ref") or "").strip()
        if target:
            eval_params["target"] = target
        if params.get("element"):
            eval_params["element"] = str(params["element"])
        if params.get("filename"):
            eval_params["filename"] = str(params["filename"])
        return eval_params
    raise ValueError(f"Unsupported Playwright action: {action}")


def _screenshot_params(params: dict[str, Any]) -> dict[str, Any]:
    screenshot_params: dict[str, Any] = {"type": str(params.get("type") or "png")}
    target = str(params.get("target") or params.get("ref") or "").strip()
    if target:
        screenshot_params["target"] = target
    if params.get("element"):
        screenshot_params["element"] = str(params["element"])
    if params.get("filename"):
        screenshot_params["filename"] = str(params["filename"])
    if params.get("full_page") is not None:
        screenshot_params["fullPage"] = bool(params["full_page"])
    elif params.get("fullPage") is not None:
        screenshot_params["fullPage"] = bool(params["fullPage"])
    return screenshot_params


def _drag_params(params: dict[str, Any]) -> dict[str, Any]:
    start_target = str(params.get("start_target") or params.get("startTarget") or "").strip()
    end_target = str(params.get("end_target") or params.get("endTarget") or "").strip()
    if not start_target or not end_target:
        raise ValueError("Playwright drag requires start_target and end_target.")
    drag_params: dict[str, Any] = {
        "startTarget": start_target,
        "endTarget": end_target,
    }
    if params.get("start_element"):
        drag_params["startElement"] = str(params["start_element"])
    elif params.get("startElement"):
        drag_params["startElement"] = str(params["startElement"])
    if params.get("end_element"):
        drag_params["endElement"] = str(params["end_element"])
    elif params.get("endElement"):
        drag_params["endElement"] = str(params["endElement"])
    return drag_params


def _tab_params(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action == "new_tab":
        tab_action = "new"
    elif action == "select_tab":
        tab_action = "select"
    elif action == "close_tab":
        tab_action = "close"
    elif action == "list_tabs":
        tab_action = "list"
    else:
        tab_action = str(
            params.get("tab_action")
            or params.get("operation")
            or params.get("command")
            or "list"
        ).strip().casefold()

    if tab_action not in {"list", "new", "close", "select"}:
        raise ValueError("Playwright tabs action must be one of: list, new, close, select.")

    tool_params: dict[str, Any] = {"action": tab_action}
    if params.get("index") not in (None, ""):
        tool_params["index"] = int(params["index"])
    if params.get("url"):
        tool_params["url"] = str(params["url"]).strip()
    return tool_params


def _element_ref_params(params: dict[str, Any]) -> dict[str, Any]:
    target = str(params.get("target") or params.get("ref") or "").strip()
    if not target:
        raise ValueError("Playwright action requires a target/ref from browser_snapshot.")
    tool_params = {"target": target}
    if params.get("element"):
        tool_params["element"] = str(params["element"])
    return tool_params


class _PlaywrightMcpClient:
    def __init__(self) -> None:
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        self._stdio_context: Any | None = None
        self._session_context: Any | None = None
        self._session: Any | None = None
        self._tool_names: set[str] = set()
        self._server_signature: tuple[str, tuple[str, ...]] | None = None

    def _lock_for_current_loop(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    async def call(self, params: dict[str, Any]) -> str:
        action = _action_name(params)
        tool_name = READ_ACTIONS.get(action) or MUTATING_ACTIONS.get(action)
        if tool_name is None:
            return f"Unsupported Playwright action: {action}."
        if action in MUTATING_ACTIONS and not _mutations_allowed():
            return f"Playwright action '{action}' requires PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true."

        call_params = _tool_params(action, params)
        timeout_action = "close_tab" if tool_name == "browser_tabs" and call_params.get("action") == "close" else action
        async with self._lock_for_current_loop():
            await self._ensure_started()
            if tool_name not in self._tool_names:
                return f"Playwright MCP server does not expose {tool_name}."
            try:
                result = await asyncio.wait_for(
                    self._session.call_tool(tool_name, call_params),
                    timeout=_mcp_action_timeout_seconds(timeout_action),
                )
            except TimeoutError:
                await self.close()
                return (
                    f"Playwright {timeout_action} timed out after "
                    f"{_mcp_action_timeout_seconds(timeout_action):g} seconds; browser session was reset."
                )
            except Exception:
                await self.close()
                raise
            return _content_text(result) or f"Playwright {action} completed."

    async def _ensure_started(self) -> None:
        server_params = _server_params()
        signature = (server_params.command, tuple(server_params.args or ()))
        if self._session is not None and self._server_signature == signature:
            return
        if self._session is not None:
            await self.close()

        self._server_signature = signature
        self._stdio_context = stdio_client(server_params)
        try:
            read, write = await self._stdio_context.__aenter__()
            self._session_context = ClientSession(read, write)
            self._session = await self._session_context.__aenter__()
            await self._session.initialize()
            self._tool_names = _tool_names(await self._session.list_tools())
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        session_context = self._session_context
        stdio_context = self._stdio_context
        self._session = None
        self._session_context = None
        self._stdio_context = None
        self._tool_names = set()
        self._server_signature = None

        if session_context is not None:
            try:
                await session_context.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug("[PLAYWRIGHT_MCP] Session close failed: %s", exc)
        if stdio_context is not None:
            try:
                await stdio_context.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug("[PLAYWRIGHT_MCP] Stdio close failed: %s", exc)


_client = _PlaywrightMcpClient()


class _PlaywrightWorker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def submit(self, coro: Any) -> concurrent.futures.Future:
        loop = self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop)

    async def shutdown_async(self) -> None:
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            return
        future = asyncio.run_coroutine_threadsafe(_client.close(), loop)
        await asyncio.wrap_future(future)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        with self._lock:
            if self._loop is loop:
                self._loop = None
                self._thread = None
                self._ready.clear()

    def shutdown(self) -> None:
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            return
        future = asyncio.run_coroutine_threadsafe(_client.close(), loop)
        future.result(timeout=get_settings().mcp_timeout_seconds)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        with self._lock:
            if self._loop is loop:
                self._loop = None
                self._thread = None
                self._ready.clear()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._thread is not None and self._thread.is_alive():
                return self._loop
            self._ready.clear()
            self._thread = threading.Thread(target=self._run_loop, name="playwright-mcp", daemon=True)
            self._thread.start()
        self._ready.wait(timeout=10)
        if self._loop is None:
            raise RuntimeError("Playwright MCP worker loop did not start.")
        return self._loop

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(_client.close())
            loop.close()


_worker = _PlaywrightWorker()


async def _run_tool_inner(params: dict[str, Any]) -> str:
    return await _client.call(params)


async def run_tool_async(params: dict[str, Any]) -> str:
    timeout = get_settings().mcp_timeout_seconds
    future: concurrent.futures.Future | None = None
    try:
        future = _worker.submit(_run_tool_inner(params))
        return await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)
    except TimeoutError:
        if future is not None:
            future.cancel()
        await _worker.shutdown_async()
        return f"Playwright MCP timed out after {timeout} seconds."
    except Exception as exc:
        logger.error("[PLAYWRIGHT_MCP] Error: %s", exc)
        await _worker.shutdown_async()
        return f"Playwright MCP failed: {exc}"


def run_tool(params: dict[str, Any]) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        timeout = get_settings().mcp_timeout_seconds
        future = _worker.submit(_run_tool_inner(params))
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            _worker.shutdown()
            return f"Playwright MCP timed out after {timeout} seconds."
        except Exception as exc:
            logger.error("[PLAYWRIGHT_MCP] Error: %s", exc)
            _worker.shutdown()
            return f"Playwright MCP failed: {exc}"
    raise RuntimeError("playwright_tools.run_tool cannot run inside an active event loop; use run_tool_async.")


async def shutdown_async() -> None:
    await _worker.shutdown_async()


def shutdown() -> None:
    _worker.shutdown()
