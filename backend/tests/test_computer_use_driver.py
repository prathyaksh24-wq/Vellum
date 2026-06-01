from __future__ import annotations

from agent.computer_use.operator import OperatorResult
from agent.computer_use.windows_driver import WindowsComputerDriver


class FakeNativeDriver:
    backend = "windows_native"

    def __init__(self):
        self.calls = []

    def health_check(self):
        return {"ok": True, "backend": self.backend, "message": "ready"}

    def activate_window(self, window_id):
        self.calls.append(("activate_window", {"window_id": window_id}))
        return OperatorResult("ok", self.backend, "activated", observation={"window": {"id": window_id}})

    def click(self, **params):
        self.calls.append(("click", params))
        if "element_index" not in params and ("x" not in params or "y" not in params):
            raise ValueError("click requires element_index or x/y coordinates.")
        return OperatorResult("ok", self.backend, "clicked", {"action": "click"}, {"window": {"id": "hwnd:1"}})

    def get_window_state(self, **params):
        self.calls.append(("get_window_state", params))
        return OperatorResult("ok", self.backend, "observed", observation={"window": {"id": "hwnd:1"}})

    def press_key(self, **params):
        self.calls.append(("press_key", params))
        return OperatorResult("ok", self.backend, "pressed", {"action": "press_key"})

    def scroll(self, **params):
        self.calls.append(("scroll", params))
        return OperatorResult("ok", self.backend, "scrolled", {"action": "scroll"})

    def drag(self, **params):
        self.calls.append(("drag", params))
        required = {"from_x", "from_y", "to_x", "to_y"}
        missing = sorted(required.difference(params))
        if missing:
            raise TypeError(f"drag missing required params: {', '.join(missing)}")
        return OperatorResult("ok", self.backend, "dragged", {"action": "drag"})


class RaisingNativeDriver:
    backend = "windows_native"

    def health_check(self):
        return {"ok": True, "backend": self.backend, "message": "ready"}

    def list_windows(self):
        raise RuntimeError("native exploded")


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


def test_windows_driver_keypress_maps_to_native_press_key():
    native_driver = FakeNativeDriver()
    driver = WindowsComputerDriver(native_driver=native_driver)

    result = driver.run_action("keypress", keys=["ctrl", "s"])

    assert native_driver.calls == [("press_key", {"key": "ctrl+s"})]
    assert result["status"] == "ok"


def test_windows_driver_double_click_maps_to_click_count_two():
    native_driver = FakeNativeDriver()
    driver = WindowsComputerDriver(native_driver=native_driver)

    result = driver.run_action("double_click", x=10, y=20)

    assert native_driver.calls == [("click", {"x": 10, "y": 20, "click_count": 2})]
    assert result["status"] == "ok"


def test_windows_driver_right_click_maps_to_right_button():
    native_driver = FakeNativeDriver()
    driver = WindowsComputerDriver(native_driver=native_driver)

    result = driver.run_action("right_click", x=10, y=20)

    assert native_driver.calls == [("click", {"x": 10, "y": 20, "button": "right"})]
    assert result["status"] == "ok"


def test_windows_driver_scroll_amount_maps_to_scroll_y():
    native_driver = FakeNativeDriver()
    driver = WindowsComputerDriver(native_driver=native_driver)

    result = driver.run_action("scroll", x=10, y=20, amount=-3)

    assert native_driver.calls == [("scroll", {"x": 10, "y": 20, "scroll_y": -3})]
    assert result["status"] == "ok"


def test_windows_driver_explicit_native_drag_coordinates_pass_through():
    native_driver = FakeNativeDriver()
    driver = WindowsComputerDriver(native_driver=native_driver)

    result = driver.run_action("drag", from_x=1, from_y=2, to_x=10, to_y=20)

    assert native_driver.calls == [("drag", {"from_x": 1, "from_y": 2, "to_x": 10, "to_y": 20})]
    assert result["status"] == "ok"


def test_windows_driver_legacy_drag_target_uses_current_pointer_context():
    native_driver = FakeNativeDriver()
    driver = WindowsComputerDriver(native_driver=native_driver)

    result = driver.run_action(
        "drag",
        x=30,
        y=40,
        current_x=10,
        current_y=20,
        duration=0.2,
        button="left",
    )

    assert native_driver.calls == [("drag", {"from_x": 10, "from_y": 20, "to_x": 30, "to_y": 40})]
    assert result["status"] == "ok"


def test_windows_driver_legacy_drag_target_without_pointer_context_is_mapped():
    native_driver = FakeNativeDriver()
    driver = WindowsComputerDriver(native_driver=native_driver)

    result = driver.run_action("drag", x=30, y=40)

    assert native_driver.calls == [("drag", {"from_x": 30, "from_y": 40, "to_x": 30, "to_y": 40})]
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


def test_windows_driver_returns_structured_error_for_missing_activate_window_id():
    driver = WindowsComputerDriver(native_driver=FakeNativeDriver())

    result = driver.run_action("activate_window")

    assert result == {
        "status": "error",
        "backend": "windows_native",
        "message": "'window_id'",
        "data": {"action": "activate_window"},
    }


def test_windows_driver_returns_structured_error_for_missing_click_target():
    driver = WindowsComputerDriver(native_driver=FakeNativeDriver())

    result = driver.run_action("click")

    assert result == {
        "status": "error",
        "backend": "windows_native",
        "message": "click requires element_index or x/y coordinates.",
        "data": {"action": "click"},
    }


def test_windows_driver_returns_structured_error_for_native_exception():
    driver = WindowsComputerDriver(native_driver=RaisingNativeDriver())

    result = driver.run_action("list_windows")

    assert result == {
        "status": "error",
        "backend": "windows_native",
        "message": "native exploded",
        "data": {"action": "list_windows"},
    }
