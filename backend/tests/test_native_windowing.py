import ctypes

import pytest

from agent.computer_use.operator import ComputerWindow
from agent.computer_use.native_windows import windowing


def test_window_id_round_trip():
    assert windowing.window_id(1234) == "hwnd:1234"
    assert windowing.parse_window_id("hwnd:1234") == 1234
    assert windowing.parse_window_id("1234") == 1234


def test_invalid_window_id_is_rejected():
    try:
        windowing.parse_window_id("window:abc")
    except ValueError as exc:
        assert "Invalid window id" in str(exc)
    else:
        raise AssertionError("parse_window_id should reject invalid ids")


def test_normalize_window_skips_empty_titles():
    result = windowing.normalize_window(
        hwnd=10,
        title="",
        pid=2,
        app="notepad.exe",
        bounds=(1, 2, 3, 4),
    )

    assert result is None


def test_normalize_window_returns_computer_window():
    result = windowing.normalize_window(
        hwnd=10,
        title="  Untitled   -   Notepad  ",
        pid=2,
        app="notepad.exe",
        bounds=(1, 2, 801, 602),
    )

    assert isinstance(result, ComputerWindow)
    assert result.id == "hwnd:10"
    assert result.title == "Untitled - Notepad"
    assert result.bounds == {"x": 1, "y": 2, "width": 800, "height": 600}


def test_normalize_window_skips_zero_or_negative_bounds():
    assert (
        windowing.normalize_window(
            hwnd=10,
            title="Untitled - Notepad",
            pid=2,
            app="notepad.exe",
            bounds=(1, 2, 1, 602),
        )
        is None
    )
    assert (
        windowing.normalize_window(
            hwnd=10,
            title="Untitled - Notepad",
            pid=2,
            app="notepad.exe",
            bounds=(10, 2, 1, 602),
        )
        is None
    )


def test_active_window_rejects_non_windows_before_accessing_user32(monkeypatch):
    class WindllTrap:
        @property
        def user32(self):
            raise AssertionError("user32 should not be accessed off Windows")

    monkeypatch.setattr(windowing, "_is_windows", lambda: False)
    monkeypatch.setattr(ctypes, "windll", WindllTrap(), raising=False)

    with pytest.raises(RuntimeError, match="Native Windows computer use requires Windows."):
        windowing.active_window()


def test_active_window_raises_when_foreground_window_is_null(monkeypatch):
    class FakeUser32:
        def GetForegroundWindow(self):
            return None

    class FakeWindll:
        user32 = FakeUser32()

    monkeypatch.setattr(windowing, "_is_windows", lambda: True)
    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)

    with pytest.raises(RuntimeError, match="No active foreground window"):
        windowing.active_window()


def test_activate_window_raises_when_set_foreground_window_fails(monkeypatch):
    class FakeUser32:
        def ShowWindow(self, hwnd, command):
            return 1

        def SetForegroundWindow(self, hwnd):
            return 0

        def GetForegroundWindow(self):
            return 20

    class FakeWindll:
        user32 = FakeUser32()

    monkeypatch.setattr(windowing, "_is_windows", lambda: True)
    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)

    with pytest.raises(RuntimeError, match="Failed to activate window: hwnd:10"):
        windowing.activate_window("hwnd:10")


def test_activate_window_raises_clear_error_when_foreground_window_is_null(monkeypatch):
    class FakeUser32:
        def ShowWindow(self, hwnd, command):
            return 1

        def SetForegroundWindow(self, hwnd):
            return 1

        def GetForegroundWindow(self):
            return None

    class FakeWindll:
        user32 = FakeUser32()

    monkeypatch.setattr(windowing, "_is_windows", lambda: True)
    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)

    with pytest.raises(RuntimeError, match="Failed to activate window: hwnd:10"):
        windowing.activate_window("hwnd:10")
