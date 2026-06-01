from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Callable

from agent.config import get_settings


def save_window_screenshot(
    hwnd: int,
    *,
    screenshot_dir: Path | None = None,
    filename: str | None = None,
    image_factory: Callable[[int], Any] | None = None,
) -> dict[str, Any]:
    directory = screenshot_dir or get_settings().computer_use_screenshot_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _filename(hwnd, filename)
    image = (image_factory or capture_window_image)(int(hwnd))
    image.save(path)
    return {
        "hwnd": int(hwnd),
        "path": str(path),
        "width": getattr(image, "width", None),
        "height": getattr(image, "height", None),
    }


def capture_window_image(hwnd: int):
    if not hasattr(__import__("ctypes"), "windll"):
        raise RuntimeError("Native window capture requires Windows.")
    return _capture_with_print_window(hwnd)


def _filename(hwnd: int, filename: str | None) -> str:
    raw = str(filename or "").strip()
    if not raw:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        raw = f"window-{int(hwnd)}-{stamp}.png"
    name = raw.replace("\\", "/").split("/")[-1]
    if not name.casefold().endswith(".png"):
        name = f"{name}.png"
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _capture_with_print_window(hwnd: int):
    import ctypes
    from ctypes import wintypes
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("GetWindowRect failed.")
    width = max(1, rect.right - rect.left)
    height = max(1, rect.bottom - rect.top)
    hdc_window = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
    gdi32.SelectObject(hdc_mem, hbmp)
    try:
        user32.PrintWindow(hwnd, hdc_mem, 2)
        bitmap_info = _bitmap_info(width, height)
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(hdc_mem, hbmp, 0, height, buffer, ctypes.byref(bitmap_info), 0)
        return Image.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1)
    finally:
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)


def _bitmap_info(width: int, height: int):
    import ctypes
    from ctypes import wintypes

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    return info
