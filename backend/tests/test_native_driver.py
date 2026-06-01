from agent.computer_use.native_windows.driver import WindowsNativeComputerDriver


class FakeWindowing:
    def __init__(self):
        self.activated = []

    def list_windows(self):
        from agent.computer_use.operator import ComputerWindow

        return [
            ComputerWindow(
                "hwnd:1",
                1,
                "notepad.exe",
                2,
                "Untitled - Notepad",
                {"x": 0, "y": 0, "width": 100, "height": 80},
            )
        ]

    def get_window(self, window_id):
        return self.list_windows()[0]

    def active_window(self):
        return self.list_windows()[0]

    def activate_window(self, window_id):
        self.activated.append(window_id)
        return self.list_windows()[0]


class FakeAccessibility:
    def get_accessibility_state(self, hwnd, include_text=True):
        return {
            "tree": "[0] Window name='Notepad'",
            "elements": [{"index": 0, "bounds": {"x": 10, "y": 20, "width": 30, "height": 40}}],
        }

    def element_center(self, state, index):
        return (25, 40)


class FakeCapture:
    def save_window_screenshot(self, hwnd, **kwargs):
        return {"path": "screen.png", "hwnd": hwnd}


class FakeInput:
    def __init__(self):
        self.calls = []

    def click(self, x, y, **kwargs):
        self.calls.append(("click", x, y, kwargs))


def test_driver_observe_returns_window_screenshot_and_accessibility():
    driver = WindowsNativeComputerDriver(
        windowing=FakeWindowing(),
        accessibility=FakeAccessibility(),
        capture=FakeCapture(),
        input_layer=FakeInput(),
    )

    result = driver.get_window_state("hwnd:1")

    assert result.status == "ok"
    assert result.backend == "windows_native"
    assert result.observation["window"]["id"] == "hwnd:1"
    assert result.observation["screenshot"]["path"] == "screen.png"
    assert "Notepad" in result.observation["accessibility"]["tree"]


def test_driver_click_element_activates_window_and_uses_element_center():
    windowing = FakeWindowing()
    input_layer = FakeInput()
    driver = WindowsNativeComputerDriver(
        windowing=windowing,
        accessibility=FakeAccessibility(),
        capture=FakeCapture(),
        input_layer=input_layer,
    )

    result = driver.click("hwnd:1", element_index=0)

    assert result.status == "ok"
    assert windowing.activated == ["hwnd:1"]
    assert input_layer.calls[0][0:3] == ("click", 25, 40)
    assert result.observation is not None
