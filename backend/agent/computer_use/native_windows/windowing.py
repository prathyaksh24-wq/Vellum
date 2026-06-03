from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from pathlib import Path

from agent.computer_use.operator import ComputerWindow

_configured_user32_ids: set[int] = set()


def window_id(hwnd: int) -> str:
    return f"hwnd:{int(hwnd)}"


def parse_window_id(value: str | int) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.startswith("hwnd:"):
        text = text.removeprefix("hwnd:")
    if not text.isdigit():
        raise ValueError(f"Invalid window id: {value}")
    return int(text)


def _hwnd_int(value) -> int:
    if value is None:
        return 0
    return int(value)


def normalize_window(
    *,
    hwnd: int,
    title: str,
    pid: int,
    app: str,
    bounds: tuple[int, int, int, int],
) -> ComputerWindow | None:
    clean_title = " ".join(str(title or "").split())
    if not clean_title:
        return None
    left, top, right, bottom = bounds
    width = max(0, int(right) - int(left))
    height = max(0, int(bottom) - int(top))
    if width <= 0 or height <= 0:
        return None
    return ComputerWindow(
        id=window_id(hwnd),
        hwnd=int(hwnd),
        app=app or "unknown",
        pid=int(pid),
        title=clean_title,
        bounds={"x": int(left), "y": int(top), "width": width, "height": height},
    )


def list_windows() -> list[ComputerWindow]:
    if not _is_windows():
        return []
    user32 = _user32()
    windows: list[ComputerWindow] = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @enum_proc
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_text(hwnd)
        pid = _window_pid(hwnd)
        app = _process_name(pid)
        bounds = _window_bounds(hwnd)
        normalized = normalize_window(
            hwnd=int(hwnd),
            title=title,
            pid=pid,
            app=app,
            bounds=bounds,
        )
        if normalized is not None:
            windows.append(normalized)
        return True

    user32.EnumWindows(callback, 0)
    return windows


def get_window(value: str | int) -> ComputerWindow:
    hwnd = parse_window_id(value)
    if not _is_windows():
        raise RuntimeError("Native Windows computer use requires Windows.")
    pid = _window_pid(hwnd)
    normalized = normalize_window(
        hwnd=hwnd,
        title=_window_text(hwnd),
        pid=pid,
        app=_process_name(pid),
        bounds=_window_bounds(hwnd),
    )
    if normalized is None:
        raise RuntimeError(f"Window is not targetable: {value}")
    return normalized


def active_window() -> ComputerWindow:
    if not _is_windows():
        raise RuntimeError("Native Windows computer use requires Windows.")
    hwnd = _hwnd_int(_user32().GetForegroundWindow())
    if hwnd == 0:
        raise RuntimeError("No active foreground window.")
    return get_window(hwnd)


def activate_window(value: str | int) -> ComputerWindow:
    hwnd = parse_window_id(value)
    if not _is_windows():
        raise RuntimeError("Native Windows computer use requires Windows.")
    user32 = _user32()
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    if not _wait_for_foreground(user32, hwnd):
        raise RuntimeError(f"Failed to activate window: {window_id(hwnd)}")
    return get_window(hwnd)


def _wait_for_foreground(
    user32,
    hwnd: int,
    timeout_seconds: float = 1.0,
    poll_interval_seconds: float = 0.05,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        if _hwnd_int(user32.GetForegroundWindow()) == hwnd:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_interval_seconds)


def _is_windows() -> bool:
    return hasattr(ctypes, "windll")


def _user32():
    user32 = ctypes.windll.user32
    _configure_user32(user32)
    return user32


def _configure_user32(user32) -> None:
    user32_id = id(user32)
    if user32_id in _configured_user32_ids:
        return
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _set_signature(user32, "EnumWindows", [enum_proc, wintypes.LPARAM], wintypes.BOOL)
    _set_signature(user32, "GetForegroundWindow", [], wintypes.HWND)
    _set_signature(user32, "GetWindowTextLengthW", [wintypes.HWND], ctypes.c_int)
    _set_signature(
        user32,
        "GetWindowTextW",
        [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int],
        ctypes.c_int,
    )
    _set_signature(
        user32,
        "GetWindowThreadProcessId",
        [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)],
        wintypes.DWORD,
    )
    _set_signature(
        user32,
        "GetWindowRect",
        [wintypes.HWND, ctypes.POINTER(wintypes.RECT)],
        wintypes.BOOL,
    )
    _set_signature(user32, "ShowWindow", [wintypes.HWND, ctypes.c_int], wintypes.BOOL)
    _set_signature(user32, "SetForegroundWindow", [wintypes.HWND], wintypes.BOOL)
    _set_signature(user32, "IsWindowVisible", [wintypes.HWND], wintypes.BOOL)
    _configured_user32_ids.add(user32_id)


def _set_signature(user32, name: str, argtypes, restype) -> None:
    function = getattr(user32, name, None)
    if function is None:
        return
    try:
        function.argtypes = argtypes
        function.restype = restype
    except AttributeError:
        pass


def _window_text(hwnd: int) -> str:
    user32 = _user32()
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _window_bounds(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    _user32().GetWindowRect(hwnd, ctypes.byref(rect))
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _process_name(pid: int) -> str:
    try:
        import psutil
    except ImportError:
        return f"pid:{pid}"
    try:
        process = psutil.Process(pid)
        return Path(process.exe()).name or process.name()
    except Exception:
        return f"pid:{pid}"
