"""Unified computer-use tool for desktop and browser control."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from agent.computer_use_runtime import computer_use_runtime
from agent.computer_use_workspace import WorkspaceActionError, workspace_worker
from agent.mcp.playwright_tools import run_tool as playwright_run
from agent.tools import desktop as desktop_tools

SAFE_DESKTOP_ACTIONS = {"permissions", "grant_permission", "screenshot", "position", "screen_size"}


def _put(params: dict[str, Any], key: str, value: Any) -> None:
    if value not in (None, ""):
        params[key] = value


def _desktop_params(
    *,
    action: str,
    x: int,
    y: int,
    text: str,
    key: str,
    keys: str,
    amount: int,
    button: str,
    duration: float,
    interval: float,
    filename: str,
    command: str,
    shell: str,
    app: str,
    target: str,
    permission: str,
    confirm: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {"action": action}
    if action in {"move", "click", "double_click", "right_click", "drag"}:
        params["x"] = x
        params["y"] = y
    if action in {"move", "drag"}:
        params["duration"] = duration
    if action in {"click", "drag"}:
        _put(params, "button", button)
    if action == "scroll":
        params["amount"] = amount
    if action == "type":
        params["text"] = text
        params["interval"] = interval
    if action == "press_key":
        params["key"] = key
    if action == "hotkey":
        params["keys"] = keys or key
    if action == "screenshot":
        _put(params, "filename", filename)
    if action in {"open_terminal", "run_terminal_command"}:
        _put(params, "command", command or text)
        _put(params, "shell", shell)
    if action == "open_app":
        _put(params, "app", app or target or text)
    if action == "grant_permission":
        _put(params, "permission", permission)
        params["confirm"] = confirm
    return params


def _browser_params(
    *,
    action: str,
    target: str,
    ref: str,
    element: str,
    text: str,
    key: str,
    url: str,
    tab_action: str,
    index: str,
    width: int,
    height: int,
    filename: str,
    full_page: bool,
    level: str,
    function: str,
    fields_json: str,
    start_target: str,
    end_target: str,
    start_element: str,
    end_element: str,
) -> dict[str, Any]:
    params: dict[str, Any] = {"action": "snapshot" if action == "observe" else action}
    _put(params, "target", target or ref)
    _put(params, "element", element)
    _put(params, "text", text)
    _put(params, "key", key)
    _put(params, "url", url)
    _put(params, "tab_action", tab_action)
    _put(params, "index", index)
    if action == "resize":
        params["width"] = width
        params["height"] = height
    _put(params, "filename", filename)
    if action == "screenshot" and full_page:
        params["full_page"] = True
    if action in {"console", "console_messages"}:
        params["level"] = level
    _put(params, "function", function)
    _put(params, "fields_json", fields_json)
    _put(params, "start_target", start_target)
    _put(params, "end_target", end_target)
    _put(params, "start_element", start_element)
    _put(params, "end_element", end_element)
    return params


def _workspace_params(
    *,
    action: str,
    url: str,
    target: str,
    element: str,
    text: str,
    command: str,
    filename: str,
    amount: int,
    submit: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {"action": action}
    _put(params, "url", url)
    _put(params, "target", target)
    _put(params, "element", element)
    _put(params, "text", text)
    _put(params, "command", command or text)
    _put(params, "filename", filename)
    if amount:
        params["amount"] = amount
    if submit:
        params["submit"] = True
    return params


@tool
def computer_use(
    mode: str = "desktop",
    action: str = "screenshot",
    target: str = "",
    ref: str = "",
    element: str = "",
    text: str = "",
    key: str = "",
    keys: str = "",
    url: str = "",
    tab_action: str = "",
    index: str = "",
    x: int = 0,
    y: int = 0,
    width: int = 0,
    height: int = 0,
    amount: int = 0,
    button: str = "",
    duration: float = 0,
    interval: float = 0,
    filename: str = "",
    command: str = "",
    shell: str = "",
    app: str = "",
    permission: str = "",
    confirm: bool = False,
    submit: bool = False,
    full_page: bool = False,
    level: str = "info",
    function: str = "",
    fields_json: str = "",
    start_target: str = "",
    end_target: str = "",
    start_element: str = "",
    end_element: str = "",
) -> str:
    """Control the local desktop, visible workspace, or persistent browser.

    Use mode='workspace' for visible computer-use tasks inside Vellum's
    workspace: browser.open/browser.navigate, input.click/input.type,
    input.scroll, terminal.run, and screen.screenshot. Use mode='desktop' for
    OS-level host screen/mouse/keyboard actions. Use mode='browser' for direct
    Playwright MCP page automation. Desktop input actions require
    COMPUTER_USE_ALLOW_DESKTOP=true. If a desktop action returns a permission
    request, ask the user and only then call action='grant_permission' with
    confirm=True.
    """

    selected_mode = mode.strip().casefold()
    if selected_mode == "desktop":
        params = _desktop_params(
            action=action,
            x=x,
            y=y,
            text=text,
            key=key,
            keys=keys,
            amount=amount,
            button=button,
            duration=duration,
            interval=interval,
            filename=filename,
            command=command,
            shell=shell,
            app=app,
            target=target,
            permission=permission,
            confirm=confirm,
        )
        computer_use_runtime.record_event(
            "tool_start",
            f"computer_use desktop {action} started.",
            tool="computer_use",
            data={"mode": "desktop", "action": action, "params": _public_params(params)},
        )
        if action not in SAFE_DESKTOP_ACTIONS and not computer_use_runtime.is_enabled():
            result = "Computer use mode is disabled. Ask the user to enable computer use before desktop control."
            computer_use_runtime.record_event(
                "tool_blocked",
                result,
                tool="computer_use",
                data={"mode": "desktop", "action": action},
            )
            return result
        result = desktop_tools.run_desktop_action(params)
        computer_use_runtime.record_event(
            "tool_result",
            f"computer_use desktop {action} finished.",
            tool="computer_use",
            data={"mode": "desktop", "action": action, "result": result},
        )
        return result
    if selected_mode == "workspace":
        params = _workspace_params(
            action=action,
            url=url,
            target=target or ref,
            element=element,
            text=text,
            command=command,
            filename=filename,
            amount=amount,
            submit=submit,
        )
        computer_use_runtime.record_event(
            "tool_start",
            f"computer_use workspace {action} started.",
            tool="computer_use",
            data={"mode": "workspace", "action": action, "params": _public_params(params)},
        )
        try:
            workspace_result = workspace_worker.run(params)
        except WorkspaceActionError as exc:
            message = str(exc)
            computer_use_runtime.record_event(
                "tool_error",
                message,
                tool="computer_use",
                data={"mode": "workspace", "action": action},
            )
            return message
        computer_use_runtime.record_event(
            "tool_result",
            f"computer_use workspace {action} finished.",
            tool="computer_use",
            data={"mode": "workspace", "action": action, "result": workspace_result.data},
        )
        return workspace_result.message
    if selected_mode == "browser":
        params = _browser_params(
            action=action,
            target=target,
            ref=ref,
            element=element,
            text=text,
            key=key,
            url=url,
            tab_action=tab_action,
            index=index,
            width=width,
            height=height,
            filename=filename,
            full_page=full_page,
            level=level,
            function=function,
            fields_json=fields_json,
            start_target=start_target,
            end_target=end_target,
            start_element=start_element,
            end_element=end_element,
        )
        if params.get("fields_json"):
            try:
                json.loads(str(params["fields_json"]))
            except json.JSONDecodeError:
                return "computer_use fields_json must be valid JSON."
        computer_use_runtime.record_event(
            "tool_start",
            f"computer_use browser {action} started.",
            tool="computer_use",
            data={"mode": "browser", "action": action, "params": _public_params(params)},
        )
        result = playwright_run(params)
        computer_use_runtime.record_event(
            "tool_result",
            f"computer_use browser {action} finished.",
            tool="computer_use",
            data={"mode": "browser", "action": action, "result": result},
        )
        return result
    return "computer_use mode must be desktop, workspace, or browser."


def _public_params(params: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(params)
    for key in ("text", "command", "fields_json"):
        if key in redacted and redacted[key]:
            redacted[key] = "[redacted]"
    return redacted
