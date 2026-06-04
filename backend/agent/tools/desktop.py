"""Compatibility helpers for desktop computer-use permissions.

Desktop input and observation moved to the native Windows driver. This module
keeps permission state and clear migration errors for callers that still import
the old desktop tool path.
"""

from __future__ import annotations

import json
from typing import Any

from agent.config import get_settings


NATIVE_DRIVER_MESSAGE = (
    "Desktop computer use has moved to the native Windows driver. "
    "Use agent.computer_use.windows_driver.WindowsComputerDriver."
)

MUTATING_DESKTOP_ACTIONS = {
    "move",
    "click",
    "double_click",
    "right_click",
    "drag",
    "scroll",
    "type",
    "type_text",
    "press_key",
    "keypress",
    "hotkey",
    "activate_window",
    "open_terminal",
    "run_terminal_command",
    "open_app",
    "close_window",
    "close_app",
    "switch_app",
    "switch_browser_tab",
    "close_browser_tab",
}

CONTROL_PERMISSIONS = {
    "move": "desktop_control",
    "click": "desktop_control",
    "double_click": "desktop_control",
    "right_click": "desktop_control",
    "drag": "desktop_control",
    "scroll": "desktop_control",
    "type": "desktop_control",
    "type_text": "desktop_control",
    "press_key": "desktop_control",
    "keypress": "desktop_control",
    "hotkey": "desktop_control",
    "activate_window": "desktop_control",
    "open_terminal": "terminal",
    "run_terminal_command": "terminal",
    "open_app": "open_apps",
    "close_window": "desktop_control",
    "close_app": "open_apps",
    "switch_app": "desktop_control",
    "switch_browser_tab": "desktop_control",
    "close_browser_tab": "desktop_control",
}

KNOWN_PERMISSIONS = {"desktop_control", "terminal", "open_apps"}


def _desktop_allowed() -> bool:
    return get_settings().computer_use_allow_desktop


def _permission_file():
    path = get_settings().computer_use_screenshot_dir.parent / "permissions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_permissions() -> dict[str, bool]:
    path = _permission_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): bool(value) for key, value in data.items()}


def _save_permissions(data: dict[str, bool]) -> None:
    _permission_file().write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _runtime_permission_granted(permission: str) -> bool:
    return _load_permissions().get(permission, False)


def _grant_runtime_permission(permission: str) -> None:
    data = _load_permissions()
    data[permission] = True
    _save_permissions(data)


def _permission_param(params: dict[str, Any]) -> str:
    permission = str(params.get("permission") or "").strip().casefold().replace("-", "_")
    if not permission:
        raise ValueError("Computer use permission action requires permission.")
    if permission not in KNOWN_PERMISSIONS:
        raise ValueError(f"Computer use permission must be one of: {', '.join(sorted(KNOWN_PERMISSIONS))}.")
    return permission


def _confirm_param(params: dict[str, Any]) -> bool:
    value = params.get("confirm", False)
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "yes", "y", "1", "grant", "granted"}
    return bool(value)


def _permission_status() -> str:
    data = _load_permissions()
    parts = [f"{permission}={str(data.get(permission, False)).lower()}" for permission in sorted(KNOWN_PERMISSIONS)]
    return "Computer use permissions: " + ", ".join(parts) + "."


def _permission_required(permission: str) -> str:
    return (
        f"Computer use permission required: {permission}. Ask the user to grant this, then call "
        "computer_use(mode='desktop', action='grant_permission', "
        f"permission='{permission}', confirm=True)."
    )


def run_desktop_action(_params: dict[str, Any]) -> str:
    return NATIVE_DRIVER_MESSAGE
