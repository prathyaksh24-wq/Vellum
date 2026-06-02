"""Unified computer-use tool for desktop and browser control."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from agent.computer_use.input_guard import computer_use_input_guard
from agent.computer_use.windows_driver import WindowsComputerDriver
from agent.computer_use_runtime import computer_use_runtime
from agent.computer_use_workspace import WorkspaceActionError, workspace_worker
from agent.mcp.playwright_tools import run_tool as playwright_run
from agent.tools import desktop as desktop_tools

NATIVE_DESKTOP_ACTIONS = {
    "activate_window",
    "click",
    "double_click",
    "drag",
    "hotkey",
    "keypress",
    "list_apps",
    "list_windows",
    "observe",
    "press_key",
    "right_click",
    "screenshot",
    "scroll",
    "type",
    "type_text",
}

NATIVE_MUTATING_DESKTOP_ACTIONS = {
    "activate_window",
    "click",
    "double_click",
    "drag",
    "keypress",
    "press_key",
    "right_click",
    "scroll",
    "type",
    "type_text",
}

desktop_driver = WindowsComputerDriver()

REMOVED_DESKTOP_ACTION_MESSAGE = desktop_tools.NATIVE_DRIVER_MESSAGE


def _put(params: dict[str, Any], key: str, value: Any) -> None:
    if value not in (None, ""):
        params[key] = value


def _desktop_action_name(action: str) -> str:
    return str(action or "screenshot").strip().casefold().replace("-", "_")


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
    element_index: int | None,
    tab_action: str,
    permission: str,
    confirm: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {"action": action}
    if action in {
        "activate_window",
        "click",
        "double_click",
        "right_click",
        "drag",
        "observe",
        "keypress",
        "press_key",
        "hotkey",
        "scroll",
        "screenshot",
        "type",
        "type_text",
    }:
        _put(params, "target", target)
    if element_index is not None:
        params["element_index"] = element_index
    if action in {"move", "click", "double_click", "right_click", "drag"}:
        if element_index is None:
            params["x"] = x
            params["y"] = y
    if action in {"move", "drag"}:
        params["duration"] = duration
    if action in {"click", "drag"}:
        _put(params, "button", button)
    if action == "scroll":
        params["amount"] = amount
    if action in {"type", "type_text"}:
        params["text"] = text
        if interval:
            params["interval"] = interval
    if action in {"press_key", "keypress"}:
        params["key"] = key
    if action == "hotkey":
        params["keys"] = keys or key
    if action == "screenshot":
        _put(params, "filename", filename)
    if action in {"open_terminal", "run_terminal_command"}:
        _put(params, "command", command or text)
        _put(params, "shell", shell)
    if action in {"open_app", "close_app"}:
        _put(params, "app", app or target or text)
    if action in {"switch_app", "switch_browser_tab"}:
        _put(params, "direction", tab_action or target or text)
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


def _native_desktop_params(params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    driver_params = dict(params)
    driver_action = str(driver_params.pop("action"))
    target = driver_params.pop("target", "")
    if target:
        driver_params["window_id"] = target
    if "amount" in driver_params:
        driver_params["scroll_y"] = driver_params.pop("amount")
    if "keys" in driver_params and "key" not in driver_params:
        driver_params["key"] = driver_params.pop("keys")
    return driver_action, driver_params


def _is_mutating_desktop_action(action: str) -> bool:
    return action in desktop_tools.MUTATING_DESKTOP_ACTIONS or action in NATIVE_MUTATING_DESKTOP_ACTIONS


def _desktop_safety_block(action: str) -> str | None:
    if _is_mutating_desktop_action(action) and not desktop_tools._desktop_allowed():
        return f"Desktop action '{action}' requires COMPUTER_USE_ALLOW_DESKTOP=true."
    required_permission = desktop_tools.CONTROL_PERMISSIONS.get(action)
    if required_permission is None and action in NATIVE_MUTATING_DESKTOP_ACTIONS:
        required_permission = "desktop_control"
    if required_permission and not desktop_tools._runtime_permission_granted(required_permission):
        return desktop_tools._permission_required(required_permission)
    return None


def _desktop_permission_result(action: str, params: dict[str, Any]) -> str | None:
    if action == "permissions":
        return desktop_tools._permission_status()
    if action != "grant_permission":
        return None
    try:
        permission = desktop_tools._permission_param(params)
    except ValueError as exc:
        return str(exc)
    if not desktop_tools._confirm_param(params):
        return desktop_tools._permission_required(permission)
    desktop_tools._grant_runtime_permission(permission)
    return f"Computer use permission granted: {permission}."


def _public_result(result: Any) -> Any:
    if isinstance(result, dict):
        redacted: dict[str, Any] = {}
        for key, value in result.items():
            if key in {"text", "command", "fields_json"} and value:
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _public_result(value)
        return redacted
    if isinstance(result, list):
        return [_public_result(value) for value in result]
    return result


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
    element_index: int | None = None,
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
        desktop_action = _desktop_action_name(action)
        params = _desktop_params(
            action=desktop_action,
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
            element_index=element_index,
            tab_action=tab_action,
            permission=permission,
            confirm=confirm,
        )
        computer_use_runtime.record_event(
            "tool_start",
            f"computer_use desktop {desktop_action} started.",
            tool="computer_use",
            data={"mode": "desktop", "action": desktop_action, "params": _public_params(params)},
        )
        permission_result = _desktop_permission_result(desktop_action, params)
        if permission_result is not None:
            computer_use_runtime.record_event(
                "tool_result",
                f"computer_use desktop {desktop_action} finished.",
                tool="computer_use",
                data={"mode": "desktop", "action": desktop_action, "result": permission_result},
            )
            return permission_result
        if desktop_action not in NATIVE_DESKTOP_ACTIONS:
            computer_use_runtime.record_event(
                "tool_result",
                f"computer_use desktop {desktop_action} finished.",
                tool="computer_use",
                data={"mode": "desktop", "action": desktop_action, "result": REMOVED_DESKTOP_ACTION_MESSAGE},
            )
            return REMOVED_DESKTOP_ACTION_MESSAGE
        if _is_mutating_desktop_action(desktop_action) and not computer_use_runtime.is_enabled():
            result = "Computer use mode is disabled. Ask the user to enable computer use before desktop control."
            computer_use_runtime.record_event(
                "tool_blocked",
                result,
                tool="computer_use",
                data={"mode": "desktop", "action": desktop_action},
            )
            return result
        if _is_mutating_desktop_action(desktop_action):
            guard_status = computer_use_input_guard.status()
            if not guard_status.get("lease_active", False):
                result = "Computer use exclusive control is not active. Enable computer use again before desktop control."
                computer_use_runtime.record_event(
                    "tool_blocked",
                    result,
                    tool="computer_use",
                    data={"mode": "desktop", "action": desktop_action, "input_guard": guard_status},
                )
                return result
            computer_use_input_guard.heartbeat()
        safety_result = _desktop_safety_block(desktop_action)
        if safety_result:
            computer_use_runtime.record_event(
                "tool_blocked",
                safety_result,
                tool="computer_use",
                data={"mode": "desktop", "action": desktop_action},
            )
            return safety_result
        driver_action, driver_params = _native_desktop_params(params)
        native_result = desktop_driver.run_action(driver_action, **driver_params)
        computer_use_runtime.record_event(
            "tool_result",
            f"computer_use desktop {desktop_action} finished.",
            tool="computer_use",
            data={"mode": "desktop", "action": desktop_action, "result": _public_result(native_result)},
        )
        if isinstance(native_result, dict) and native_result.get("message"):
            return str(native_result["message"])
        return str(native_result)
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
