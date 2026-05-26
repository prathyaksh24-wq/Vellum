"""Local OS desktop computer-use primitives."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any

from agent.config import get_settings


MUTATING_DESKTOP_ACTIONS = {
    "move",
    "click",
    "double_click",
    "right_click",
    "drag",
    "scroll",
    "type",
    "press_key",
    "hotkey",
    "open_terminal",
    "run_terminal_command",
    "open_app",
}

CONTROL_PERMISSIONS = {
    "move": "desktop_control",
    "click": "desktop_control",
    "double_click": "desktop_control",
    "right_click": "desktop_control",
    "drag": "desktop_control",
    "scroll": "desktop_control",
    "type": "desktop_control",
    "press_key": "desktop_control",
    "hotkey": "desktop_control",
    "open_terminal": "terminal",
    "run_terminal_command": "terminal",
    "open_app": "open_apps",
}

KNOWN_PERMISSIONS = {"desktop_control", "terminal", "open_apps"}
_persistent_overlay_process: subprocess.Popen | None = None


def _pyautogui():
    try:
        import pyautogui
    except ImportError as exc:
        raise RuntimeError(
            "Desktop computer use requires pyautogui. Install backend dependencies first."
        ) from exc
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    return pyautogui


def _desktop_allowed() -> bool:
    return get_settings().computer_use_allow_desktop


def _activity_overlay_enabled() -> bool:
    return get_settings().computer_use_activity_overlay


def _screenshot_dir():
    path = get_settings().computer_use_screenshot_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def _action_name(params: dict[str, Any]) -> str:
    return str(params.get("action") or "screenshot").strip().casefold().replace("-", "_")


def _int_param(params: dict[str, Any], name: str) -> int:
    value = params.get(name)
    if value in (None, ""):
        raise ValueError(f"Desktop action requires {name}.")
    return int(value)


def _float_param(params: dict[str, Any], name: str, default: float = 0) -> float:
    value = params.get(name)
    if value in (None, ""):
        return default
    return float(value)


def _button(params: dict[str, Any], default: str = "left") -> str:
    button = str(params.get("button") or default).strip().casefold()
    if button not in {"left", "right", "middle"}:
        raise ValueError("Desktop mouse button must be left, right, or middle.")
    return button


def _filename(params: dict[str, Any]) -> str:
    raw = str(params.get("filename") or "").strip()
    if not raw:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        raw = f"desktop-{stamp}.png"
    name = raw.replace("\\", "/").split("/")[-1]
    if not name.casefold().endswith(".png"):
        name = f"{name}.png"
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _keys(params: dict[str, Any]) -> list[str]:
    raw = params.get("keys", params.get("key", ""))
    if isinstance(raw, list):
        keys = [str(key).strip() for key in raw if str(key).strip()]
    else:
        keys = [part.strip() for part in str(raw).replace("+", ",").split(",") if part.strip()]
    if not keys:
        raise ValueError("Desktop hotkey requires keys.")
    return keys


def _command(params: dict[str, Any]) -> str:
    command = str(params.get("command") or params.get("text") or "").strip()
    if not command:
        raise ValueError("Desktop terminal command requires command.")
    return command


def _app(params: dict[str, Any]) -> str:
    app = str(params.get("app") or params.get("target") or params.get("text") or "").strip()
    if not app:
        raise ValueError("Desktop open_app requires app.")
    return app


def _shell(params: dict[str, Any]) -> str:
    shell = str(params.get("shell") or "powershell").strip().casefold()
    if shell not in {"powershell", "pwsh", "cmd"}:
        raise ValueError("Desktop terminal shell must be powershell, pwsh, or cmd.")
    return shell


def _terminal_args(command: str = "", shell: str = "powershell") -> list[str]:
    if os.name == "nt":
        shell_exe = {"powershell": "powershell.exe", "pwsh": "pwsh.exe", "cmd": "cmd.exe"}[shell]
        if shell == "cmd":
            shell_args = [shell_exe, "/k"]
            if command:
                shell_args.append(command)
        else:
            shell_args = [shell_exe, "-NoExit"]
            if command:
                shell_args.extend(["-Command", command])
        wt = shutil.which("wt.exe")
        if wt:
            return [wt, *shell_args]
        return shell_args

    unix_shell = os.environ.get("SHELL") or "bash"
    if command:
        return [unix_shell, "-lc", f"{command}; exec {unix_shell}"]
    return [unix_shell]


def _launch_terminal_command(command: str = "", shell: str = "powershell") -> None:
    args = _terminal_args(command, shell)
    if os.name == "nt":
        _shell_execute(args[0], args[1:])
        return
    subprocess.Popen(args)


def _shell_execute(file: str, params: list[str] | None = None) -> None:
    if os.name != "nt":
        subprocess.Popen([file, *(params or [])])
        return
    try:
        import ctypes
    except ImportError as exc:
        raise RuntimeError("Windows app launching requires ctypes.") from exc

    joined = subprocess.list2cmdline(params or [])
    result = ctypes.windll.shell32.ShellExecuteW(None, "open", file, joined, None, 1)
    if result <= 32:
        raise RuntimeError(f"Windows ShellExecute failed with code {result}.")


def _app_alias(app: str) -> tuple[str, list[str]]:
    normalized = re.sub(r"\s+", " ", app.strip().casefold())
    aliases: dict[str, tuple[str, list[str]]] = {
        "terminal": ("wt.exe", []),
        "windows terminal": ("wt.exe", []),
        "powershell": ("powershell.exe", ["-NoExit"]),
        "command prompt": ("cmd.exe", ["/k"]),
        "cmd": ("cmd.exe", ["/k"]),
        "notepad": ("notepad.exe", []),
        "calculator": ("calc.exe", []),
        "calc": ("calc.exe", []),
        "settings": ("ms-settings:", []),
        "file explorer": ("explorer.exe", []),
        "explorer": ("explorer.exe", []),
    }
    return aliases.get(normalized, (app, []))


def _launch_app(app: str) -> None:
    if os.name == "nt":
        executable, args = _app_alias(app)
        try:
            _shell_execute(executable, args)
            return
        except Exception:
            _launch_app_via_start_menu(app)
            return
    subprocess.Popen([app])


def _launch_app_via_start_menu(app: str) -> None:
    pg = _pyautogui()
    pg.hotkey("win")
    time.sleep(0.35)
    pg.write(app, interval=0.01)
    time.sleep(0.15)
    pg.press("enter")



def _overlay_script() -> str:
    return r"""
import ctypes
import tkinter as tk

root = tk.Tk()
root.overrideredirect(True)
root.attributes("-topmost", True)
root.configure(bg="black")
root.attributes("-transparentcolor", "black")
width = root.winfo_screenwidth()
height = root.winfo_screenheight()
root.geometry(f"{width}x{height}+0+0")
canvas = tk.Canvas(root, width=width, height=height, bg="black", highlightthickness=0, bd=0)
canvas.pack(fill="both", expand=True)
color = "#d97746"
soft = "#f1b27a"

try:
    hwnd = root.winfo_id()
    user32 = ctypes.windll.user32
    exstyle = user32.GetWindowLongW(hwnd, -20)
    user32.SetWindowLongW(hwnd, -20, exstyle | 0x00080000 | 0x00000020 | 0x00000080)
except Exception:
    pass

def draw(step=0):
    canvas.delete("glow")
    pulse = step % 26
    width_outer = 7 + min(pulse, 26 - pulse) // 3
    canvas.create_rectangle(6, 6, width - 6, height - 6, outline=color, width=width_outer, tags="glow")
    canvas.create_rectangle(18, 18, width - 18, height - 18, outline=soft, width=2, tags="glow")
    root.after(80, draw, step + 1)

draw()
root.mainloop()
"""


def _start_overlay_process() -> subprocess.Popen | None:
    try:
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        process = subprocess.Popen([sys.executable, "-c", _overlay_script()], **kwargs)
        time.sleep(0.12)
        return process
    except Exception:
        return None


def start_activity_overlay() -> str:
    global _persistent_overlay_process
    if not _activity_overlay_enabled():
        return "Computer-use activity overlay is disabled."
    if _persistent_overlay_process is not None and _persistent_overlay_process.poll() is None:
        return "Computer-use activity overlay is already visible."
    _persistent_overlay_process = _start_overlay_process()
    if _persistent_overlay_process is None:
        return "Computer-use activity overlay could not be started."
    return "Computer-use activity overlay started."


def stop_activity_overlay() -> str:
    global _persistent_overlay_process
    process = _persistent_overlay_process
    _persistent_overlay_process = None
    if process is None or process.poll() is not None:
        return "Computer-use activity overlay is not running."
    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
    return "Computer-use activity overlay stopped."


@contextmanager
def _activity_overlay():
    if not _activity_overlay_enabled():
        yield
        return

    process: subprocess.Popen | None = None
    try:
        if _persistent_overlay_process is None or _persistent_overlay_process.poll() is not None:
            process = _start_overlay_process()
    except Exception:
        process = None
    try:
        yield
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()


def _overlay_for(action: str):
    if action in MUTATING_DESKTOP_ACTIONS:
        return _activity_overlay()
    return nullcontext()


def _perform_desktop_action(action: str, params: dict[str, Any]) -> str:
    if action == "permissions":
        return _permission_status()
    if action == "grant_permission":
        permission = _permission_param(params)
        if not _confirm_param(params):
            return f"Computer use permission '{permission}' was not granted because confirm=True was not provided."
        _grant_runtime_permission(permission)
        return f"Computer use permission granted: {permission}."
    if action == "open_terminal":
        shell = _shell(params)
        _launch_terminal_command("", shell=shell)
        return f"Visible terminal opened with {shell}."
    if action == "run_terminal_command":
        command = _command(params)
        shell = _shell(params)
        _launch_terminal_command(command, shell=shell)
        return f"Visible terminal command started in {shell}: {command}"
    if action == "open_app":
        app = _app(params)
        _launch_app(app)
        return f"Desktop app launch requested: {app}."

    pg = _pyautogui()
    if action == "screenshot":
        path = _screenshot_dir() / _filename(params)
        pg.screenshot().save(path)
        return f"Desktop screenshot saved: {path}."
    if action == "position":
        x, y = pg.position()
        return f"Desktop mouse position: {int(x)},{int(y)}."
    if action == "screen_size":
        width, height = pg.size()
        return f"Desktop screen size: {int(width)}x{int(height)}."
    if action == "move":
        x = _int_param(params, "x")
        y = _int_param(params, "y")
        duration = _float_param(params, "duration", 0)
        pg.moveTo(x, y, duration=duration)
        return f"Desktop move completed to {x},{y}."
    if action in {"click", "double_click", "right_click"}:
        x = _int_param(params, "x")
        y = _int_param(params, "y")
        button = "right" if action == "right_click" else _button(params)
        clicks = 2 if action == "double_click" else 1
        pg.click(x=x, y=y, button=button, clicks=clicks)
        return f"Desktop {action.replace('_', ' ')} completed at {x},{y}."
    if action == "drag":
        x = _int_param(params, "x")
        y = _int_param(params, "y")
        duration = _float_param(params, "duration", 0)
        button = _button(params)
        pg.dragTo(x, y, duration=duration, button=button)
        return f"Desktop drag completed to {x},{y}."
    if action == "scroll":
        clicks = _int_param(params, "amount")
        pg.scroll(clicks)
        return f"Desktop scroll completed: {clicks}."
    if action == "type":
        text = str(params.get("text") or "")
        if not text:
            raise ValueError("Desktop type requires text.")
        interval = _float_param(params, "interval", 0)
        pg.write(text, interval=interval)
        return "Desktop type completed."
    if action == "press_key":
        key = str(params.get("key") or "").strip()
        if not key:
            raise ValueError("Desktop press_key requires key.")
        pg.press(key)
        return f"Desktop key press completed: {key}."
    if action == "hotkey":
        keys = _keys(params)
        pg.hotkey(*keys)
        return f"Desktop hotkey completed: {'+'.join(keys)}."
    return f"Unsupported desktop action: {action}."


def run_desktop_action(params: dict[str, Any]) -> str:
    action = _action_name(params)
    if action in MUTATING_DESKTOP_ACTIONS and not _desktop_allowed():
        return f"Desktop action '{action}' requires COMPUTER_USE_ALLOW_DESKTOP=true."
    required_permission = CONTROL_PERMISSIONS.get(action)
    if required_permission and not _runtime_permission_granted(required_permission):
        return _permission_required(required_permission)

    try:
        with _overlay_for(action):
            return _perform_desktop_action(action, params)
    except Exception as exc:
        return f"Desktop computer use failed: {exc}"
