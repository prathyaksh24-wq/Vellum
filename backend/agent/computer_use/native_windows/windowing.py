from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

from agent.computer_use.operator import ComputerWindow


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
    user32 = ctypes.windll.user32
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
    normalized = normalize_window(
        hwnd=hwnd,
        title=_window_text(hwnd),
        pid=_window_pid(hwnd),
        app=_process_name(_window_pid(hwnd)),
        bounds=_window_bounds(hwnd),
    )
    if normalized is None:
        raise RuntimeError(f"Window is not targetable: {value}")
    return normalized


def active_window() -> ComputerWindow:
    hwnd = int(ctypes.windll.user32.GetForegroundWindow())
    return get_window(hwnd)


def activate_window(value: str | int) -> ComputerWindow:
    hwnd = parse_window_id(value)
    if not _is_windows():
        raise RuntimeError("Native Windows computer use requires Windows.")
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    return get_window(hwnd)


def _is_windows() -> bool:
    return hasattr(ctypes, "windll")


def _window_text(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _window_bounds(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
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
