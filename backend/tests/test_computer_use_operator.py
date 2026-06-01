from agent.computer_use.operator import (
    CodexComputerUseAdapter,
    ComputerWindow,
    OperatorResult,
)


def test_computer_window_serializes_to_public_dict():
    window = ComputerWindow(
        id="hwnd:100",
        hwnd=100,
        app="notepad.exe",
        pid=42,
        title="Untitled - Notepad",
        bounds={"x": 1, "y": 2, "width": 800, "height": 600},
    )

    assert window.to_dict()["id"] == "hwnd:100"
    assert window.to_dict()["bounds"]["width"] == 800


def test_operator_result_carries_backend_and_observation():
    result = OperatorResult(
        status="ok",
        backend="windows_native",
        message="Observed.",
        data={"window_id": "hwnd:100"},
        observation={"accessibility_tree": "button 1"},
    )

    assert result.to_dict()["backend"] == "windows_native"
    assert result.to_dict()["observation"]["accessibility_tree"] == "button 1"


def test_codex_adapter_is_disabled_by_default():
    adapter = CodexComputerUseAdapter()

    assert adapter.health_check()["ok"] is False
    assert adapter.list_windows().status == "unavailable"
    assert "unavailable" in adapter.list_windows().message.casefold()
