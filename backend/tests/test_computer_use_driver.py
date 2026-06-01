from __future__ import annotations

from agent.computer_use.operator import OperatorResult
from agent.computer_use.windows_driver import WindowsComputerDriver


class FakeNativeDriver:
    backend = "windows_native"

    def __init__(self):
        self.calls = []

    def health_check(self):
        return {"ok": True, "backend": self.backend, "message": "ready"}

    def click(self, **params):
        self.calls.append(("click", params))
        return OperatorResult("ok", self.backend, "clicked", {"action": "click"}, {"window": {"id": "hwnd:1"}})

    def get_window_state(self, **params):
        self.calls.append(("get_window_state", params))
        return OperatorResult("ok", self.backend, "observed", observation={"window": {"id": "hwnd:1"}})

    def press_key(self, **params):
        self.calls.append(("press_key", params))
        return OperatorResult("ok", self.backend, "pressed", {"action": "press_key"})


def test_windows_driver_delegates_structured_actions_to_native_driver():
    native_driver = FakeNativeDriver()
    driver = WindowsComputerDriver(native_driver=native_driver)

    result = driver.run_action("click", window_id="hwnd:1", x=10, y=20)

    assert native_driver.calls == [("click", {"window_id": "hwnd:1", "x": 10, "y": 20})]
    assert result == {
        "status": "ok",
        "backend": "windows_native",
        "message": "clicked",
        "data": {"action": "click"},
        "observation": {"window": {"id": "hwnd:1"}},
    }


def test_windows_driver_observe_uses_native_window_state():
    native_driver = FakeNativeDriver()
    driver = WindowsComputerDriver(native_driver=native_driver)

    result = driver.run_action("screenshot", window_id="hwnd:1")

    assert native_driver.calls == [("get_window_state", {"window_id": "hwnd:1", "include_screenshot": True})]
    assert result["status"] == "ok"
    assert result["observation"]["window"]["id"] == "hwnd:1"


def test_windows_driver_hotkey_maps_to_native_press_key():
    native_driver = FakeNativeDriver()
    driver = WindowsComputerDriver(native_driver=native_driver)

    result = driver.run_action("hotkey", key="ctrl+s")

    assert native_driver.calls == [("press_key", {"key": "ctrl+s"})]
    assert result["status"] == "ok"


def test_windows_driver_health_check_delegates_to_native_driver():
    driver = WindowsComputerDriver(native_driver=FakeNativeDriver())

    result = driver.health_check()

    assert result == {"ok": True, "backend": "windows_native", "message": "ready"}


def test_windows_driver_reports_unsupported_native_actions():
    driver = WindowsComputerDriver(native_driver=FakeNativeDriver())

    result = driver.run_action("open_app", app="notepad")

    assert result == {
        "status": "unsupported",
        "message": "Unsupported native desktop action: open_app",
        "data": {"action": "open_app", "app": "notepad"},
        "backend": "windows_native",
    }
