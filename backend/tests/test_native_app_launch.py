import pytest

from agent.computer_use.native_windows import app_launch
from agent.computer_use.operator import ComputerWindow


def make_window(app="notepad.exe", title="Untitled - Notepad"):
    return ComputerWindow(
        "hwnd:1",
        1,
        app,
        2,
        title,
        {"x": 0, "y": 0, "width": 100, "height": 80},
    )


def test_resolve_notepad_alias():
    resolved = app_launch.resolve_app("notepad")

    assert resolved.executable == "notepad.exe"
    assert resolved.match_terms == ("notepad", "notepad.exe")


def test_resolve_brave_alias_prefers_existing_candidate():
    existing = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

    resolved = app_launch.resolve_app("brave browser", exists=lambda candidate: candidate == existing)

    assert resolved.executable == existing
    assert "brave" in resolved.match_terms
    assert "brave.exe" in resolved.match_terms


def test_resolve_explicit_existing_exe_path(tmp_path):
    executable = tmp_path / "ExampleApp.exe"
    executable.write_text("")

    resolved = app_launch.resolve_app(str(executable))

    assert resolved.executable == str(executable)
    assert resolved.match_terms == ("exampleapp", "exampleapp.exe")


def test_resolve_explicit_missing_exe_path_raises(tmp_path):
    executable = tmp_path / "MissingApp.exe"

    with pytest.raises(FileNotFoundError, match="Executable does not exist"):
        app_launch.resolve_app(str(executable))


def test_wait_for_launched_window_returns_first_matching_window():
    first = make_window(app="other.exe", title="Other")
    second = make_window(app="notepad.exe", title="Untitled - Notepad")
    calls = iter([[first], [first, second]])

    result = app_launch.wait_for_launched_window(
        ("notepad", "notepad.exe"),
        list_windows=lambda: next(calls),
        timeout=0.2,
        poll_interval=0,
    )

    assert result == second


def test_wait_for_launched_window_times_out():
    with pytest.raises(TimeoutError, match="Timed out waiting for launched app window"):
        app_launch.wait_for_launched_window(
            ("notepad",),
            list_windows=lambda: [make_window(app="other.exe", title="Other")],
            timeout=0,
            poll_interval=0,
        )


def test_wait_for_launched_window_clamps_zero_poll_interval(monkeypatch):
    sleep_calls = []
    windows = iter([[make_window(app="other.exe", title="Other")], [make_window()]])
    monkeypatch.setattr(app_launch.time, "sleep", sleep_calls.append)

    result = app_launch.wait_for_launched_window(
        ("notepad",),
        list_windows=lambda: next(windows),
        timeout_seconds=0.02,
        poll_interval_seconds=0,
    )

    assert result.app == "notepad.exe"
    assert sleep_calls == [0.01]
