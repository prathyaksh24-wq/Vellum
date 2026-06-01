from __future__ import annotations

import ctypes
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


def capture_window_image(hwnd: int, *, ctypes_module=ctypes):
    if not hasattr(ctypes_module, "windll"):
        raise RuntimeError("Native window capture requires Windows.")
    return _capture_with_print_window(
        hwnd,
        user32=ctypes_module.windll.user32,
        gdi32=ctypes_module.windll.gdi32,
    )


def _filename(hwnd: int, filename: str | None) -> str:
    raw = str(filename or "").strip()
    if not raw:
        raw = _default_filename(hwnd)
    name = raw.replace("\\", "/").split("/")[-1]
    if not name:
        return _default_filename(hwnd)
    if not name.casefold().endswith(".png"):
        name = f"{name}.png"
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    if not sanitized.strip("._-"):
        return _default_filename(hwnd)
    return sanitized


def _default_filename(hwnd: int) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"window-{int(hwnd)}-{stamp}.png"


def _capture_with_print_window(hwnd: int, *, user32=None, gdi32=None, image_module=None):
    from ctypes import wintypes

    if user32 is None:
        user32 = ctypes.windll.user32
    if gdi32 is None:
        gdi32 = ctypes.windll.gdi32
    if image_module is None:
        from PIL import Image as image_module

    _configure_win32_apis(user32, gdi32)

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("GetWindowRect failed.")
    width = max(1, rect.right - rect.left)
    height = max(1, rect.bottom - rect.top)
    hdc_window = user32.GetWindowDC(hwnd)
    if not hdc_window:
        raise RuntimeError("GetWindowDC failed.")
    hdc_mem = None
    hbmp = None
    old_object = None
    selected_bitmap = False
    buffer = ctypes.create_string_buffer(width * height * 4)
    bitmap_info = _bitmap_info(width, height)
    try:
        hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
        if not hdc_mem:
            raise RuntimeError("CreateCompatibleDC failed.")
        hbmp = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
        if not hbmp:
            raise RuntimeError("CreateCompatibleBitmap failed.")
        old_object = gdi32.SelectObject(hdc_mem, hbmp)
        if _is_failed_gdi_object(old_object):
            raise RuntimeError("SelectObject failed.")
        selected_bitmap = True
        if not user32.PrintWindow(hwnd, hdc_mem, 2):
            raise RuntimeError("PrintWindow failed.")
        scanlines = gdi32.GetDIBits(
            hdc_mem,
            hbmp,
            0,
            height,
            buffer,
            ctypes.byref(bitmap_info),
            0,
        )
        if scanlines != height:
            raise RuntimeError("GetDIBits failed.")
        return image_module.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1)
    finally:
        if selected_bitmap:
            gdi32.SelectObject(hdc_mem, old_object)
        if hbmp:
            gdi32.DeleteObject(hbmp)
        if hdc_mem:
            gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)


def _configure_win32_apis(user32, gdi32) -> None:
    from ctypes import wintypes

    hwnd = wintypes.HWND
    hdc = wintypes.HDC
    hbitmap = wintypes.HBITMAP
    hgdiobj = wintypes.HGDIOBJ
    lpvoid = wintypes.LPVOID
    uint = wintypes.UINT
    bool_ = wintypes.BOOL

    user32.GetWindowRect.argtypes = [hwnd, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = bool_
    user32.GetWindowDC.argtypes = [hwnd]
    user32.GetWindowDC.restype = hdc
    user32.ReleaseDC.argtypes = [hwnd, hdc]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.PrintWindow.argtypes = [hwnd, hdc, uint]
    user32.PrintWindow.restype = bool_

    gdi32.CreateCompatibleDC.argtypes = [hdc]
    gdi32.CreateCompatibleDC.restype = hdc
    gdi32.CreateCompatibleBitmap.argtypes = [hdc, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = hbitmap
    gdi32.SelectObject.argtypes = [hdc, hgdiobj]
    gdi32.SelectObject.restype = hgdiobj
    gdi32.GetDIBits.argtypes = [hdc, hbitmap, uint, uint, lpvoid, lpvoid, uint]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [hgdiobj]
    gdi32.DeleteObject.restype = bool_
    gdi32.DeleteDC.argtypes = [hdc]
    gdi32.DeleteDC.restype = bool_


def _is_failed_gdi_object(handle) -> bool:
    return not handle or handle in {-1, ctypes.c_void_p(-1).value}


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
