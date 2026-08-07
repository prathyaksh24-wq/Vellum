"""Playwright MCP browser automation wrapper.

The tool surface mirrors Hermes' browser toolset (browser_navigate,
browser_snapshot, browser_click, browser_type, browser_scroll, browser_press,
browser_back, browser_get_images, browser_vision, browser_console,
browser_cdp, browser_dialog) implemented on top of the persistent Playwright
MCP browser.

Behavior notes (Hermes parity):
- snapshots are accessibility trees with @e1-style refs; full snapshots over
  BROWSER_SNAPSHOT_BUDGET characters are truncated, the complete tree is saved
  to the browser cache, and the output points the agent at read_file paging.
- sessions are reaped after BROWSER_INACTIVITY_TIMEOUT seconds of no activity
  (a background check every BROWSER_CLEANUP_INTERVAL seconds).
- headed mode (BROWSER_HEADED=true) launches a visible browser window.
- BROWSER_CDP_URL attaches to a running Chromium-family browser via CDP and
  enables browser_cdp plus pending-dialog detection (browser_dialog).
- actions that mutate page state (click, type, press, select, hover, drag,
  evaluate, cdp, dialog) require PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import json
import logging
import shlex
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent.config import _resolve_against_repo, get_settings

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
    "dialog": "browser_dialog",
    "cdp": "browser_cdp",
}

CLOSE_ACTIONS = {"close", "close_tab"}

# Read actions fulfilled through browser_evaluate rather than a dedicated MCP tool.
EVALUATE_ACTIONS = {"scroll", "get_images"}


def _server_params() -> StdioServerParameters:
    settings = get_settings()
    args = shlex.split(settings.playwright_mcp_args)
    if not settings.browser_headed and "--headless" not in args and "--headed" not in args:
        args.append("--headless")
    cdp_url = str(settings.browser_cdp_url or "").strip()
    if cdp_url and "--cdp-endpoint" not in args:
        args.append("--cdp-endpoint")
        args.append(cdp_url)
    return StdioServerParameters(
        command=settings.playwright_mcp_command,
        args=args,
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


def _cache_root() -> Path:
    return _resolve_against_repo(get_settings().browser_cache_dir)


def _cleanup_cache(directory: Path, older_than_seconds: float) -> None:
    try:
        now = time.time()
        for path in directory.glob("*"):
            try:
                if now - path.stat().st_mtime > older_than_seconds:
                    path.unlink()
            except OSError:
                continue
    except OSError:
        pass


def _write_snapshot_cache(text: str) -> Path:
    cache = _cache_root() / "web"
    cache.mkdir(parents=True, exist_ok=True)
    _cleanup_cache(cache, older_than_seconds=24 * 3600)
    path = cache / f"snapshot-{datetime.now():%Y%m%d-%H%M%S-%f}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _save_screenshot_image(result: Any) -> Path | None:
    """Save an image content block from a screenshot result into the cache.

    Mirrors Hermes' screenshot persistence: files live under the browser
    cache's screenshots/ directory and are cleaned up after 24 hours.
    """
    cache = _cache_root() / "screenshots"
    cache.mkdir(parents=True, exist_ok=True)
    _cleanup_cache(cache, older_than_seconds=24 * 3600)
    for item in getattr(result, "content", None) or []:
        if getattr(item, "type", None) != "image":
            continue
        data = getattr(item, "data", None)
        if not data:
            continue
        mime = getattr(item, "mimeType", None) or "image/png"
        ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
        path = cache / f"vision-{datetime.now():%Y%m%d-%H%M%S-%f}.{ext}"
        try:
            path.write_bytes(base64.b64decode(data))
        except Exception as exc:
            logger.error("[PLAYWRIGHT_MCP] Screenshot save failed: %s", exc)
            return None
        return path
    return None


def _format_images(raw: str) -> str:
    try:
        images = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw or "No images found on this page."
    if not isinstance(images, list) or not images:
        return "No images found on this page."
    lines = []
    for image in images:
        if not isinstance(image, dict):
            continue
        src = str(image.get("src") or "")
        alt = str(image.get("alt") or "")
        size = ""
        if image.get("width") or image.get("height"):
            size = f" ({image.get('width')}x{image.get('height')})"
        if alt and src:
            lines.append(f"- {alt}: {src}{size}")
        elif src:
            lines.append(f"- {src}{size}")
        else:
            lines.append(f"- {alt}{size}")
    return "\n".join(lines) or "No images found on this page."


def _decorate_snapshot(text: str) -> str:
    """Append pending dialogs and enforce the per-page snapshot budget."""
    if not text:
        return text
    dialogs = _cdp.pending_dialogs_text()
    if dialogs:
        text = text.rstrip() + "\n" + dialogs
    budget = max(int(get_settings().browser_snapshot_budget), 1000)
    if len(text) <= budget:
        return text
    full_path = _write_snapshot_cache(text)
    cut = text[:budget]
    note = (
        f"\n\n[Snapshot truncated at {budget} characters — the same per-page budget Hermes uses. "
        f"Full snapshot saved to {full_path}. Call read_file with path \"{full_path}\" to page "
        f"through the complete accessibility tree, including element refs beyond the cut.]"
    )
    return cut + note


def _tool_params(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action == "navigate":
        url = str(params.get("url") or params.get("query") or "").strip()
        if not url:
            raise ValueError("Playwright navigate requires a url.")
        return {"url": url}
    if action == "snapshot":
        snapshot_params: dict[str, Any] = {}
        if params.get("full") is not None:
            snapshot_params["full"] = bool(params["full"])
        return snapshot_params
    if action in {"back", "forward", "reload", "close"}:
        return {}
    if action == "scroll":
        direction = str(params.get("direction") or "down").strip().casefold()
        if direction not in {"up", "down"}:
            raise ValueError("Playwright scroll direction must be 'up' or 'down'.")
        sign = "+" if direction == "down" else "-"
        return {
            "direction": direction,
            "function": f"() => window.scrollBy(0, {sign}Math.max(window.innerHeight * 0.8, 100))",
        }
    if action == "get_images":
        return {
            "function": (
                "() => Array.from(document.images).map((img) => ({"
                " src: img.currentSrc || img.src, alt: img.alt,"
                " width: img.naturalWidth, height: img.naturalHeight }))"
            )
        }
    if action == "vision":
        return {}
    if action in {"screenshot", "take_screenshot"}:
        return _screenshot_params(params)
    if action == "resize":
        return {
            "width": int(params.get("width") or 0),
            "height": int(params.get("height") or 0),
        }
    if action == "console":
        expression = str(params.get("expression") or "").strip()
        if expression:
            return {"expression": expression}
        console_params: dict[str, Any] = {"level": str(params.get("level") or "info")}
        if params.get("all") is not None:
            console_params["all"] = bool(params["all"])
        if params.get("clear") is not None:
            console_params["clear"] = bool(params["clear"])
        if params.get("filename"):
            console_params["filename"] = str(params["filename"])
        return console_params
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
        if params.get("clear") is not None:
            tool_params["clear"] = bool(params["clear"])
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
    if action == "cdp":
        method = str(params.get("method") or "").strip()
        if not method:
            raise ValueError("Playwright cdp requires a method.")
        cdp_params: dict[str, Any] = {"method": method}
        raw_params = str(params.get("params") or "").strip()
        if raw_params:
            try:
                cdp_params["params"] = json.loads(raw_params)
            except json.JSONDecodeError:
                cdp_params["params"] = {"expression": raw_params}
        if params.get("target_id"):
            cdp_params["target_id"] = str(params["target_id"])
        if params.get("frame_id"):
            cdp_params["frame_id"] = str(params["frame_id"])
        return cdp_params
    if action == "dialog":
        dialog_action = str(params.get("dialog_action") or "accept").strip().casefold()
        if dialog_action not in {"accept", "dismiss"}:
            raise ValueError("Playwright dialog action must be 'accept' or 'dismiss'.")
        dialog_params: dict[str, Any] = {"dialog_action": dialog_action}
        if params.get("prompt_text"):
            dialog_params["prompt_text"] = str(params["prompt_text"])
        return dialog_params
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


class _CdpSupervisor:
    """Persistent CDP connection for dialog handling and raw browser_cdp calls.

    Mirrors Hermes' CDP supervisor: one WebSocket per session that subscribes
    to Page/Runtime events so pending native dialogs (alert/confirm/prompt/
    beforeunload) surface in browser_snapshot output and can be answered with
    browser_dialog. Only active when BROWSER_CDP_URL is configured.
    """

    def __init__(self) -> None:
        self._ws: Any = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._sessions: dict[str, str] = {}
        self._dialog: dict[str, Any] | None = None
        self._dismiss_task: asyncio.Task | None = None

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def cdp_url(self) -> str:
        return str(get_settings().browser_cdp_url or "").strip()

    async def ensure_connected(self) -> bool:
        url = self.cdp_url()
        if not url:
            return False
        if self._ws is not None:
            return True
        import websockets

        ws_url = await self._resolve_ws_url(url)
        try:
            self._ws = await websockets.connect(
                ws_url,
                open_timeout=10,
                close_timeout=5,
                max_size=None,
            )
        except Exception as exc:
            logger.error("[PLAYWRIGHT_CDP] Connect failed: %s", exc)
            self._ws = None
            return False
        asyncio.get_running_loop().create_task(self._read_loop())
        await self.call("Page.enable", {})
        await self.call("Runtime.enable", {})
        return True

    async def _resolve_ws_url(self, url: str) -> str:
        if url.startswith("ws://") or url.startswith("wss://"):
            return url
        base = url.rstrip("/")
        try:
            import httpx

            response = await asyncio.to_thread(lambda: httpx.get(f"{base}/json/version", timeout=5))
            ws_url = (response.json() or {}).get("webSocketDebuggerUrl")
            if ws_url:
                return ws_url
        except Exception as exc:
            logger.debug("[PLAYWRIGHT_CDP] version probe failed: %s", exc)
        return f"{base.replace('http', 'ws', 1)}/devtools/browser"

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        if not await self.ensure_connected():
            raise RuntimeError(
                "CDP endpoint not reachable; browser_cdp requires BROWSER_CDP_URL (e.g. http://127.0.0.1:9222)."
            )
        if self._ws is None:
            raise RuntimeError("CDP supervisor is not connected.")
        self._next_id += 1
        message_id = self._next_id
        message: dict[str, Any] = {"id": message_id, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[message_id] = future
        try:
            await self._ws.send(json.dumps(message))
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(message_id, None)

    async def attach_target(self, target_id: str) -> str:
        cached = self._sessions.get(target_id)
        if cached:
            return cached
        response = await self.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        session_id = (response.get("result") or {}).get("sessionId")
        if not session_id:
            raise RuntimeError(f"Target.attachToTarget failed: {response}")
        self._sessions[target_id] = session_id
        return session_id

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if "id" in message:
                    future = self._pending.pop(message["id"], None)
                    if future is not None and not future.done():
                        future.set_result(message)
                    continue
                await self._handle_event(message)
        except Exception as exc:
            logger.debug("[PLAYWRIGHT_CDP] read loop ended: %s", exc)
        finally:
            await self.disconnect()

    async def _handle_event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params") or {}
        if method == "Page.javascriptDialogOpening":
            self._dialog = {
                "id": f"d-{int(time.monotonic() * 1000)}",
                "type": str(params.get("type") or "alert"),
                "message": str(params.get("message") or ""),
                "opened_at": time.monotonic(),
            }
            policy = get_settings().browser_dialog_policy
            if policy == "auto_dismiss":
                await self.call("Page.handleJavaScriptDialog", {"accept": False})
            elif policy == "auto_accept":
                await self.call("Page.handleJavaScriptDialog", {"accept": True})
            else:
                self._schedule_auto_dismiss()
        elif method == "Page.javascriptDialogClosed":
            self._dialog = None
            if self._dismiss_task is not None:
                self._dismiss_task.cancel()
                self._dismiss_task = None

    def _schedule_auto_dismiss(self) -> None:
        if self._dismiss_task is not None and not self._dismiss_task.done():
            return
        timeout = float(get_settings().browser_dialog_timeout_s)

        async def _auto_dismiss() -> None:
            await asyncio.sleep(timeout)
            if self._dialog is not None:
                await self.call("Page.handleJavaScriptDialog", {"accept": False})

        self._dismiss_task = asyncio.get_running_loop().create_task(_auto_dismiss())

    async def respond_to_dialog(self, action: str, prompt_text: str = "") -> dict[str, Any] | None:
        if not await self.ensure_connected():
            raise RuntimeError("CDP endpoint not reachable.")
        if self._dialog is None:
            return None
        dialog = self._dialog
        accept = action in {"accept", "ok", "okay"}
        params: dict[str, Any] = {"accept": accept}
        if accept and prompt_text:
            params["promptText"] = prompt_text
        await self.call("Page.handleJavaScriptDialog", params)
        return dialog

    def pending_dialogs_text(self) -> str:
        if self._dialog is None:
            return ""
        dialog = self._dialog
        return (
            f'\npending_dialogs: [{{"id": "{dialog["id"]}", "type": "{dialog["type"]}", '
            f'"message": {json.dumps(dialog["message"])}}}]'
        )

    async def disconnect(self) -> None:
        if self._dismiss_task is not None:
            self._dismiss_task.cancel()
            self._dismiss_task = None
        ws = self._ws
        self._ws = None
        self._pending = {}
        self._sessions = {}
        self._dialog = None
        if ws is not None:
            try:
                await ws.close()
            except Exception as exc:
                logger.debug("[PLAYWRIGHT_CDP] Close failed: %s", exc)


_cdp = _CdpSupervisor()


class _PlaywrightMcpClient:
    def __init__(self) -> None:
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        self._stdio_context: Any | None = None
        self._session_context: Any | None = None
        self._session: Any | None = None
        self._tool_names: set[str] = set()
        self._server_signature: tuple[str, tuple[str, ...]] | None = None
        self._last_activity = time.monotonic()
        self._busy = False

    def _lock_for_current_loop(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    async def reap_if_idle(self) -> None:
        """Close the browser session after BROWSER_INACTIVITY_TIMEOUT idle."""
        if self._session is None or self._busy:
            return
        idle = time.monotonic() - self._last_activity
        timeout = float(get_settings().browser_inactivity_timeout)
        if idle >= timeout:
            logger.info("[PLAYWRIGHT_MCP] Closing idle browser session after %.0fs idle.", idle)
            await self.close()

    async def call(self, params: dict[str, Any]) -> str:
        action = _action_name(params)

        if action in EVALUATE_ACTIONS:
            call_params = _tool_params(action, params)
            async with self._lock_for_current_loop():
                self._busy = True
                self._last_activity = time.monotonic()
                try:
                    return await self._call_evaluate(action, call_params)
                finally:
                    self._busy = False

        if action == "vision":
            async with self._lock_for_current_loop():
                self._busy = True
                self._last_activity = time.monotonic()
                try:
                    return await self._call_vision(params)
                finally:
                    self._busy = False

        if action == "console":
            call_params = _tool_params(action, params)
            if "expression" in call_params:
                async with self._lock_for_current_loop():
                    self._busy = True
                    self._last_activity = time.monotonic()
                    try:
                        return await self._call_evaluate("console", {"function": call_params["expression"]})
                    finally:
                        self._busy = False
            async with self._lock_for_current_loop():
                self._busy = True
                self._last_activity = time.monotonic()
                try:
                    return await self._call_mcp("browser_console_messages", call_params, action, retry_without_clear=True)
                finally:
                    self._busy = False

        if action == "cdp":
            if not _mutations_allowed():
                return "Playwright action 'cdp' requires PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true."
            cdp_params = _tool_params(action, params)
            return await self._call_cdp(cdp_params)

        if action == "dialog":
            if not _mutations_allowed():
                return "Playwright action 'dialog' requires PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true."
            dialog_params = _tool_params(action, params)
            return await self._call_dialog(dialog_params)

        tool_name = READ_ACTIONS.get(action) or MUTATING_ACTIONS.get(action)
        if tool_name is None:
            return f"Unsupported Playwright action: {action}."
        if action in MUTATING_ACTIONS and not _mutations_allowed():
            return f"Playwright action '{action}' requires PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true."

        call_params = _tool_params(action, params)
        timeout_action = "close_tab" if tool_name == "browser_tabs" and call_params.get("action") == "close" else action
        async with self._lock_for_current_loop():
            self._busy = True
            self._last_activity = time.monotonic()
            try:
                await self._ensure_started()
                if tool_name not in self._tool_names:
                    return f"Playwright MCP server does not expose {tool_name}."
                if action == "type":
                    await self._clear_field_if_requested(call_params)
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
                text = _content_text(result)
                if action == "snapshot":
                    text = _decorate_snapshot(text)
                return text or f"Playwright {action} completed."
            finally:
                self._busy = False

    async def _clear_field_if_requested(self, call_params: dict[str, Any]) -> None:
        """Hermes' browser_type clears the field before typing."""
        if not call_params.pop("clear", False):
            return
        if "browser_evaluate" not in self._tool_names:
            return
        evaluate_params: dict[str, Any] = {"function": "(el) => { el.value = ''; }"}
        if call_params.get("target"):
            evaluate_params["target"] = call_params["target"]
        try:
            await self._session.call_tool("browser_evaluate", evaluate_params)
        except Exception as exc:
            logger.debug("[PLAYWRIGHT_MCP] Pre-type clear failed: %s", exc)

    async def _call_evaluate(self, action: str, params: dict[str, Any]) -> str:
        function = str(params.get("function") or "").strip()
        if not function:
            return f"Playwright {action} requires a function."
        await self._ensure_started()
        if "browser_evaluate" not in self._tool_names:
            return "Playwright MCP server does not expose browser_evaluate."
        evaluate_params: dict[str, Any] = {"function": function}
        try:
            result = await asyncio.wait_for(
                self._session.call_tool("browser_evaluate", evaluate_params),
                timeout=_mcp_action_timeout_seconds(action),
            )
        except TimeoutError:
            await self.close()
            return (
                f"Playwright {action} timed out after "
                f"{_mcp_action_timeout_seconds(action):g} seconds; browser session was reset."
            )
        except Exception:
            await self.close()
            raise
        text = _content_text(result)
        if action == "get_images":
            return _format_images(text)
        if action == "scroll":
            direction = str(params.get("direction") or "down")
            return f"Scrolled {direction}."
        return text or f"Playwright {action} completed."

    async def _call_vision(self, params: dict[str, Any]) -> str:
        screenshot_params: dict[str, Any] = {}
        if params.get("full_page") is not None:
            screenshot_params["fullPage"] = bool(params["full_page"])
        await self._ensure_started()
        if "browser_take_screenshot" not in self._tool_names:
            return "Playwright MCP server does not expose browser_take_screenshot."
        try:
            result = await asyncio.wait_for(
                self._session.call_tool("browser_take_screenshot", screenshot_params),
                timeout=_mcp_action_timeout_seconds("screenshot"),
            )
        except TimeoutError:
            await self.close()
            return (
                f"Playwright vision timed out after "
                f"{_mcp_action_timeout_seconds('screenshot'):g} seconds; browser session was reset."
            )
        except Exception:
            await self.close()
            raise
        path = _save_screenshot_image(result)
        if path is None:
            return _content_text(result) or "Playwright vision completed."
        return (
            f"Screenshot saved to {path}.\n"
            "Use a vision-capable model or open the file to inspect visual state "
            "that the accessibility tree does not capture (CAPTCHAs, charts, layouts)."
        )

    async def _call_mcp(
        self,
        tool_name: str,
        call_params: dict[str, Any],
        action: str,
        retry_without_clear: bool = False,
    ) -> str:
        await self._ensure_started()
        if tool_name not in self._tool_names:
            return f"Playwright MCP server does not expose {tool_name}."
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, call_params),
                timeout=_mcp_action_timeout_seconds(action),
            )
        except TimeoutError:
            await self.close()
            return (
                f"Playwright {action} timed out after "
                f"{_mcp_action_timeout_seconds(action):g} seconds; browser session was reset."
            )
        except Exception:
            if retry_without_clear and call_params.pop("clear", None):
                result = await self._session.call_tool(tool_name, call_params)
            else:
                await self.close()
                raise
        return _content_text(result) or f"Playwright {action} completed."

    async def _call_cdp(self, cdp_params: dict[str, Any]) -> str:
        method = cdp_params["method"]
        params = cdp_params.get("params") or {}
        target_id = cdp_params.get("target_id") or ""
        frame_id = cdp_params.get("frame_id") or ""
        try:
            if frame_id:
                return (
                    "CDP frame_id routing is not supported by this bridge; "
                    "use Runtime.evaluate on the top-level target (omit frame_id) instead."
                )
            session_id = None
            if target_id:
                session_id = await _cdp.attach_target(target_id)
            response = await _cdp.call(method, params, session_id=session_id)
        except Exception as exc:
            logger.error("[PLAYWRIGHT_CDP] browser_cdp failed: %s", exc)
            return f"browser_cdp failed: {exc}"
        if "error" in response:
            error = response["error"]
            return f"CDP {method} error: {error.get('message', error)}"
        result = response.get("result") or {}
        if not result:
            return f"CDP {method} completed."
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _call_dialog(self, dialog_params: dict[str, Any]) -> str:
        action = dialog_params["dialog_action"]
        prompt_text = dialog_params.get("prompt_text", "")
        try:
            dialog = await _cdp.respond_to_dialog(action, prompt_text)
        except RuntimeError as exc:
            logger.debug("[PLAYWRIGHT_CDP] browser_dialog unavailable: %s", exc)
            return (
                "Pending dialogs are not detectable on this backend (no CDP endpoint). "
                "Configure BROWSER_CDP_URL to enable dialog handling; the default Playwright "
                "backend auto-dismisses native dialogs."
            )
        except Exception as exc:
            logger.error("[PLAYWRIGHT_CDP] browser_dialog failed: %s", exc)
            return f"browser_dialog failed: {exc}"
        if dialog is None:
            return "No pending dialog to respond to."
        verb = "accepted" if action == "accept" else "dismissed"
        return f"Dialog {dialog['id']} ({dialog['type']}) {verb}: {dialog['message']}"

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

        await _cdp.disconnect()
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


async def _reaper_loop() -> None:
    interval = max(float(get_settings().browser_cleanup_interval), 5.0)
    try:
        while True:
            await asyncio.sleep(interval)
            await _client.reap_if_idle()
    except asyncio.CancelledError:
        pass


class _PlaywrightWorker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._reaper: asyncio.Task | None = None

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
            self._reaper = loop.create_task(_reaper_loop())
            loop.run_forever()
        finally:
            if self._reaper is not None:
                self._reaper.cancel()
            if self._reaper is not None:
                loop.run_until_complete(
                    asyncio.gather(self._reaper, _client.close(), return_exceptions=True)
                )
            else:
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
