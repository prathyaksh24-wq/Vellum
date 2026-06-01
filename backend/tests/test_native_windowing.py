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
        title="Untitled - Notepad",
        pid=2,
        app="notepad.exe",
        bounds=(1, 2, 801, 602),
    )

    assert isinstance(result, ComputerWindow)
    assert result.id == "hwnd:10"
    assert result.bounds == {"x": 1, "y": 2, "width": 800, "height": 600}
