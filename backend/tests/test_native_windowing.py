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


def test_activate_window_waits_for_delayed_foreground(monkeypatch):
    class FakeUser32:
        def __init__(self):
            self.foreground_results = [0, None, 10]

        def ShowWindow(self, hwnd, command):
            return 1

        def SetForegroundWindow(self, hwnd):
            return 1

        def GetForegroundWindow(self):
            return self.foreground_results.pop(0)

    class FakeWindll:
        user32 = FakeUser32()

    sleep_calls = []
    expected = ComputerWindow(
        id="hwnd:10",
        hwnd=10,
        app="brave.exe",
        pid=123,
        title="YouTube",
        bounds={"x": 0, "y": 0, "width": 800, "height": 600},
    )
    monkeypatch.setattr(windowing, "_is_windows", lambda: True)
    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)
    monkeypatch.setattr(windowing.time, "sleep", sleep_calls.append)
    monkeypatch.setattr(windowing, "get_window", lambda hwnd: expected)

    assert windowing.activate_window("hwnd:10") is expected
    assert sleep_calls == [0.05]


def test_activate_window_succeeds_when_set_foreground_false_but_foreground_eventually_matches(
    monkeypatch,
):
    class FakeUser32:
        def __init__(self):
            self.foreground_results = [20, 10]

        def ShowWindow(self, hwnd, command):
            return 1

        def SetForegroundWindow(self, hwnd):
            return 0

        def GetForegroundWindow(self):
            return self.foreground_results.pop(0)

    class FakeWindll:
        user32 = FakeUser32()

    expected = ComputerWindow(
        id="hwnd:10",
        hwnd=10,
        app="brave.exe",
        pid=123,
        title="YouTube",
        bounds={"x": 0, "y": 0, "width": 800, "height": 600},
    )
    monkeypatch.setattr(windowing, "_is_windows", lambda: True)
    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)
    monkeypatch.setattr(windowing.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(windowing, "get_window", lambda hwnd: expected)

    assert windowing.activate_window("hwnd:10") is expected


def test_activate_window_uses_thread_attach_when_initial_foreground_fails(monkeypatch):
    target_hwnd = 10
    foreground_hwnd = 20

    class FakeKernel32:
        def GetCurrentThreadId(self):
            return 100

    class FakeUser32:
        def __init__(self):
            self.foreground = foreground_hwnd
            self.attached = []
            self.detached = []
            self.thread_ids = {target_hwnd: 200, foreground_hwnd: 300}

        def ShowWindow(self, hwnd, command):
            return 1

        def SetForegroundWindow(self, hwnd):
            if self.attached:
                self.foreground = hwnd
                return 1
            return 0

        def GetForegroundWindow(self):
            return self.foreground

        def GetWindowThreadProcessId(self, hwnd, _pid):
            return self.thread_ids[hwnd]

        def AttachThreadInput(self, source_thread, target_thread, attach):
            if attach:
                self.attached.append((source_thread, target_thread))
            else:
                self.detached.append((source_thread, target_thread))
            return 1

        def BringWindowToTop(self, hwnd):
            return 1

    class FakeWindll:
        user32 = FakeUser32()
        kernel32 = FakeKernel32()

    expected = ComputerWindow(
        id="hwnd:10",
        hwnd=10,
        app="brave.exe",
        pid=123,
        title="YouTube",
        bounds={"x": 0, "y": 0, "width": 800, "height": 600},
    )
    monkeypatch.setattr(windowing, "_is_windows", lambda: True)
    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)
    monkeypatch.setattr(windowing, "get_window", lambda hwnd: expected)

    assert windowing.activate_window(f"hwnd:{target_hwnd}") is expected
    assert ctypes.windll.user32.attached == [(100, 200), (100, 300)]
    assert ctypes.windll.user32.detached == [(100, 300), (100, 200)]


def test_activate_window_detaches_thread_input_when_bring_to_top_fails_or_foreground_never_matches(
    monkeypatch,
):
    target_hwnd = 10
    foreground_hwnd = 20

    class FakeKernel32:
        def GetCurrentThreadId(self):
            return 100

    class FakeUser32:
        def __init__(self):
            self.detached = []

        def ShowWindow(self, hwnd, command):
            return 1

        def SetForegroundWindow(self, hwnd):
            return 0

        def GetForegroundWindow(self):
            return foreground_hwnd

        def GetWindowThreadProcessId(self, hwnd, _pid):
            return {target_hwnd: 200, foreground_hwnd: 300}[hwnd]

        def AttachThreadInput(self, source_thread, target_thread, attach):
            if not attach:
                self.detached.append((source_thread, target_thread))
            return 1

        def BringWindowToTop(self, hwnd):
            return 0

    class FakeWindll:
        user32 = FakeUser32()
        kernel32 = FakeKernel32()

    monkeypatch.setattr(windowing, "_is_windows", lambda: True)
    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)
    monkeypatch.setattr(windowing.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="Failed to activate window: hwnd:10"):
        windowing.activate_window(f"hwnd:{target_hwnd}")

    assert ctypes.windll.user32.detached == [(100, 300), (100, 200)]


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
