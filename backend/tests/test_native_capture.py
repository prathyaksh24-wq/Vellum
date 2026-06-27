from pathlib import Path
import ctypes
from types import SimpleNamespace

import pytest

from agent.computer_use.native_windows import capture


class FakeImage:
    def __init__(self):
        self.saved_to = None

    def save(self, path):
        self.saved_to = Path(path)
        Path(path).write_bytes(b"fake-png")


def test_screenshot_filename_is_sanitized(tmp_path):
    fake = FakeImage()

    result = capture.save_window_screenshot(
        100,
        screenshot_dir=tmp_path,
        filename="../bad name.png",
        image_factory=lambda hwnd: fake,
    )

    assert result["path"].endswith("bad_name.png")
    assert fake.saved_to.name == "bad_name.png"


def test_screenshot_filename_adds_png_extension_and_falls_back_when_empty(tmp_path):
    no_extension = FakeImage()

    result = capture.save_window_screenshot(
        100,
        screenshot_dir=tmp_path,
        filename="folder\\report name",
        image_factory=lambda hwnd: no_extension,
    )

    assert Path(result["path"]).name == "report_name.png"
    assert no_extension.saved_to.name == "report_name.png"

    empty_name = FakeImage()

    result = capture.save_window_screenshot(
        100,
        screenshot_dir=tmp_path,
        filename="///",
        image_factory=lambda hwnd: empty_name,
    )

    assert Path(result["path"]).name.startswith("window-100-")
    assert Path(result["path"]).suffix == ".png"
    assert empty_name.saved_to.name.startswith("window-100-")


def test_default_screenshot_filename_mentions_hwnd(tmp_path):
    fake = FakeImage()

    result = capture.save_window_screenshot(
        100,
        screenshot_dir=tmp_path,
        image_factory=lambda hwnd: fake,
    )

    assert "window-100-" in Path(result["path"]).name
    assert result["hwnd"] == 100


def test_capture_window_image_rejects_non_windows_ctypes():
    with pytest.raises(RuntimeError, match="requires Windows"):
        capture.capture_window_image(100, ctypes_module=SimpleNamespace())


class FakeWinFunc:
    def __init__(self, name, result=1, callback=None):
        self.name = name
        self.result = result
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        if self.callback:
            return self.callback(*args)
        return self.result


class FakeUser32:
    def __init__(self):
        self.GetWindowRect = FakeWinFunc("GetWindowRect", callback=self._get_window_rect)
        self.GetWindowDC = FakeWinFunc("GetWindowDC", result=200)
        self.ReleaseDC = FakeWinFunc("ReleaseDC", result=1)
        self.PrintWindow = FakeWinFunc("PrintWindow", result=1)

    def _get_window_rect(self, hwnd, rect_pointer):
        rect = rect_pointer._obj
        rect.left = 10
        rect.top = 20
        rect.right = 13
        rect.bottom = 22
        return 1


class FakeGdi32:
    def __init__(self):
        self.events = []
        self.CreateCompatibleDC = FakeWinFunc("CreateCompatibleDC", result=300)
        self.CreateCompatibleBitmap = FakeWinFunc("CreateCompatibleBitmap", result=400)
        self.SelectObject = FakeWinFunc("SelectObject", result=500, callback=self._select_object)
        self.GetDIBits = FakeWinFunc("GetDIBits", result=2)
        self.DeleteObject = FakeWinFunc("DeleteObject", callback=self._delete_object)
        self.DeleteDC = FakeWinFunc("DeleteDC", result=1)

    def _select_object(self, hdc, obj):
        self.events.append(("select", obj))
        return self.SelectObject.result

    def _delete_object(self, obj):
        self.events.append(("delete", obj))
        return 1


class FakeImageModule:
    def __init__(self):
        self.calls = []

    def frombuffer(self, *args):
        self.calls.append(args)
        return SimpleNamespace(width=args[1][0], height=args[1][1])


def test_configures_win32_api_signatures_with_pointer_sized_handles():
    user32 = FakeUser32()
    gdi32 = FakeGdi32()

    capture._configure_win32_apis(user32, gdi32)

    assert ctypes.sizeof(user32.GetWindowDC.argtypes[0]) == ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(user32.GetWindowDC.restype) == ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(gdi32.CreateCompatibleDC.argtypes[0]) == ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(gdi32.CreateCompatibleDC.restype) == ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(gdi32.CreateCompatibleBitmap.restype) == ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(gdi32.SelectObject.restype) == ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(gdi32.GetDIBits.argtypes[4]) == ctypes.sizeof(ctypes.c_void_p)
    for function in [
        user32.GetWindowRect,
        user32.GetWindowDC,
        user32.ReleaseDC,
        user32.PrintWindow,
        gdi32.CreateCompatibleDC,
        gdi32.CreateCompatibleBitmap,
        gdi32.SelectObject,
        gdi32.GetDIBits,
        gdi32.DeleteObject,
        gdi32.DeleteDC,
    ]:
        assert function.argtypes is not None
        assert function.restype is not None
    assert user32.GetWindowRect.restype is ctypes.wintypes.BOOL
    assert user32.ReleaseDC.restype is ctypes.c_int
    assert user32.PrintWindow.restype is ctypes.wintypes.BOOL
    assert gdi32.GetDIBits.restype is ctypes.c_int
    assert gdi32.DeleteObject.restype is ctypes.wintypes.BOOL
    assert gdi32.DeleteDC.restype is ctypes.wintypes.BOOL


def test_native_capture_restores_selected_object_before_deleting_bitmap():
    user32 = FakeUser32()
    gdi32 = FakeGdi32()
    image_module = FakeImageModule()

    image = capture._capture_with_print_window(
        100,
        user32=user32,
        gdi32=gdi32,
        image_module=image_module,
    )

    assert image.width == 3
    assert image.height == 2
    assert gdi32.events == [("select", 400), ("select", 500), ("delete", 400)]


def test_native_capture_restores_and_deletes_bitmap_after_capture_failure():
    user32 = FakeUser32()
    user32.PrintWindow.result = 0
    gdi32 = FakeGdi32()

    with pytest.raises(RuntimeError, match="PrintWindow failed"):
        capture._capture_with_print_window(
            100,
            user32=user32,
            gdi32=gdi32,
            image_module=FakeImageModule(),
        )

    assert gdi32.events == [("select", 400), ("select", 500), ("delete", 400)]


@pytest.mark.parametrize(
    ("api_name", "owner", "failing_result"),
    [
        ("GetWindowDC", "user32", 0),
        ("CreateCompatibleDC", "gdi32", 0),
        ("CreateCompatibleBitmap", "gdi32", 0),
        ("SelectObject", "gdi32", 0),
        ("SelectObject", "gdi32", -1),
        ("PrintWindow", "user32", 0),
        ("GetDIBits", "gdi32", 0),
        ("GetDIBits", "gdi32", 1),
    ],
)
def test_native_capture_raises_clear_error_for_api_failures(api_name, owner, failing_result):
    user32 = FakeUser32()
    gdi32 = FakeGdi32()
    setattr(getattr(locals()[owner], api_name), "result", failing_result)

    with pytest.raises(RuntimeError, match=f"{api_name} failed"):
        capture._capture_with_print_window(
            100,
            user32=user32,
            gdi32=gdi32,
            image_module=FakeImageModule(),
        )
