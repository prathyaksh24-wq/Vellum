import pytest

from agent.tools import desktop as desktop_tools
from agent.tools import computer_use as computer_use_tools


class FakeLeaseGuard:
    def __init__(self, *, active: bool = True) -> None:
        self.active = active
        self.heartbeats = 0

    def heartbeat(self) -> None:
        self.heartbeats += 1

    def status(self) -> dict[str, object]:
        return {"lease_active": self.active, "active": self.active}


class FakeDesktopDriver:
    def __init__(self, message: str = "native-ok") -> None:
        self.message = message
        self.calls = []

    def run_action(self, action, **params):
        allowed_params = {
            "amount",
            "button",
            "click_count",
            "duration",
            "element_index",
            "filename",
            "from_x",
            "from_y",
            "include_screenshot",
            "interval",
            "key",
            "keys",
            "scroll_y",
            "shell",
            "text",
            "to_x",
            "to_y",
            "window_id",
            "x",
            "y",
        }
        unexpected = sorted(set(params).difference(allowed_params))
        if unexpected:
            raise TypeError(f"unexpected native params: {', '.join(unexpected)}")
        self.calls.append((action, params))
        return {
            "status": "ok",
            "backend": "windows_native",
            "message": self.message,
            "data": {"action": action, **params},
        }


def test_computer_use_routes_desktop(monkeypatch):
    result = computer_use_tools.computer_use.invoke({"mode": "desktop", "action": "position"})

    assert "moved to the native Windows driver" in result


def test_computer_use_routes_desktop_observe_to_native_driver(monkeypatch):
    driver = FakeDesktopDriver("observed hwnd:1")
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "observe", "target": "hwnd:1"}
    )

    assert result == "observed hwnd:1"
    assert driver.calls == [("observe", {"window_id": "hwnd:1"})]


def test_computer_use_routes_desktop_list_windows_to_native_driver(monkeypatch):
    driver = FakeDesktopDriver("listed windows")
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)

    result = computer_use_tools.computer_use.invoke({"mode": "desktop", "action": "list_windows"})

    assert result == "listed windows"
    assert driver.calls == [("list_windows", {})]


def test_computer_use_routes_desktop_click_element_index_to_native_driver(monkeypatch):
    driver = FakeDesktopDriver("clicked element")
    guard = FakeLeaseGuard()
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", guard)
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_desktop_allowed", lambda: True)
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_runtime_permission_granted", lambda permission: True)
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "click", "target": "hwnd:1", "element_index": 2}
    )

    assert result == "clicked element"
    assert guard.heartbeats == 1
    assert driver.calls == [("click", {"window_id": "hwnd:1", "element_index": 2})]


def test_computer_use_routes_desktop_type_to_native_driver(monkeypatch):
    driver = FakeDesktopDriver("typed text")
    guard = FakeLeaseGuard()
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", guard)
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_desktop_allowed", lambda: True)
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_runtime_permission_granted", lambda permission: True)
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "type", "target": "hwnd:1", "text": "KSI"}
    )

    assert result == "typed text"
    assert guard.heartbeats == 1
    assert driver.calls == [("type", {"text": "KSI", "window_id": "hwnd:1"})]


def test_computer_use_routes_desktop_keypress_target_to_native_window_id(monkeypatch):
    driver = FakeDesktopDriver("pressed key")
    guard = FakeLeaseGuard()
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", guard)
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_desktop_allowed", lambda: True)
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_runtime_permission_granted", lambda permission: True)
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "keypress", "target": "hwnd:1", "key": "enter"}
    )

    assert result == "pressed key"
    assert guard.heartbeats == 1
    assert driver.calls == [("keypress", {"key": "enter", "window_id": "hwnd:1"})]


def test_computer_use_routes_desktop_terminal_command(monkeypatch):
    guard = FakeLeaseGuard()
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", guard)
    monkeypatch.setattr(
        computer_use_tools.desktop_tools,
        "run_desktop_action",
        lambda params: (_ for _ in ()).throw(AssertionError("legacy desktop runner should not be used")),
    )

    result = computer_use_tools.computer_use.invoke(
        {
            "mode": "desktop",
            "action": "run_terminal_command",
            "command": "claude",
            "shell": "powershell",
        }
    )

    assert "moved to the native Windows driver" in result
    assert guard.heartbeats == 1


def test_computer_use_preserves_desktop_env_gate_before_native_driver(monkeypatch):
    driver = FakeDesktopDriver("clicked element")
    guard = FakeLeaseGuard()
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", guard)
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_desktop_allowed", lambda: False)
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "click", "target": "hwnd:1", "element_index": 2}
    )

    assert "requires COMPUTER_USE_ALLOW_DESKTOP=true" in result
    assert driver.calls == []


def test_computer_use_preserves_desktop_runtime_permission_before_native_driver(monkeypatch):
    driver = FakeDesktopDriver("clicked element")
    guard = FakeLeaseGuard()
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", guard)
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_desktop_allowed", lambda: True)
    monkeypatch.setattr(
        computer_use_tools.desktop_tools,
        "_runtime_permission_granted",
        lambda permission: False,
    )
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "click", "target": "hwnd:1", "element_index": 2}
    )

    assert "Computer use permission required: desktop_control" in result
    assert driver.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "activate_window", "target": "hwnd:1"},
        {"action": "keypress", "key": "enter"},
        {"action": "type_text", "target": "hwnd:1", "text": "secret"},
    ],
)
def test_computer_use_blocks_all_native_mutating_actions_when_mode_disabled(monkeypatch, payload):
    driver = FakeDesktopDriver("native-ok")
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: False)
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)

    result = computer_use_tools.computer_use.invoke({"mode": "desktop", **payload})

    assert "Computer use mode is disabled" in result
    assert driver.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "activate_window", "target": "hwnd:1"},
        {"action": "keypress", "key": "enter"},
        {"action": "type_text", "target": "hwnd:1", "text": "secret"},
    ],
)
def test_computer_use_blocks_all_native_mutating_actions_without_lease(monkeypatch, payload):
    driver = FakeDesktopDriver("native-ok")
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", FakeLeaseGuard(active=False))
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)

    result = computer_use_tools.computer_use.invoke({"mode": "desktop", **payload})

    assert "exclusive control is not active" in result
    assert driver.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "activate_window", "target": "hwnd:1"},
        {"action": "keypress", "key": "enter"},
        {"action": "type_text", "target": "hwnd:1", "text": "secret"},
    ],
)
def test_computer_use_preserves_env_gate_for_all_native_mutating_actions(monkeypatch, payload):
    driver = FakeDesktopDriver("native-ok")
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", FakeLeaseGuard())
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_desktop_allowed", lambda: False)
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)

    result = computer_use_tools.computer_use.invoke({"mode": "desktop", **payload})

    assert "requires COMPUTER_USE_ALLOW_DESKTOP=true" in result
    assert driver.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "activate_window", "target": "hwnd:1"},
        {"action": "keypress", "key": "enter"},
        {"action": "type_text", "target": "hwnd:1", "text": "secret"},
    ],
)
def test_computer_use_preserves_runtime_permission_for_all_native_mutating_actions(monkeypatch, payload):
    driver = FakeDesktopDriver("native-ok")
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", FakeLeaseGuard())
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_desktop_allowed", lambda: True)
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_runtime_permission_granted", lambda permission: False)
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)

    result = computer_use_tools.computer_use.invoke({"mode": "desktop", **payload})

    assert "Computer use permission required: desktop_control" in result
    assert driver.calls == []


def test_computer_use_redacts_native_result_payloads_in_events(monkeypatch):
    events = []
    driver = FakeDesktopDriver("typed text")
    guard = FakeLeaseGuard()
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", guard)
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_desktop_allowed", lambda: True)
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_runtime_permission_granted", lambda permission: True)
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)
    monkeypatch.setattr(
        computer_use_tools.computer_use_runtime,
        "record_event",
        lambda event_type, message, **kwargs: events.append((event_type, message, kwargs)),
    )

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "type", "target": "hwnd:1", "text": "super secret"}
    )

    assert result == "typed text"
    result_events = [event for event in events if event[0] == "tool_result"]
    assert result_events
    assert result_events[-1][2]["data"]["result"]["data"]["text"] == "[redacted]"


def test_computer_use_blocks_desktop_mutation_when_mode_disabled(monkeypatch):
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: False)

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "click", "x": 10, "y": 20}
    )

    assert "Computer use mode is disabled" in result
    assert "enable computer use" in result


def test_computer_use_blocks_desktop_mutation_when_exclusive_lease_missing(monkeypatch):
    driver = FakeDesktopDriver("desktop-ok")
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", FakeLeaseGuard(active=False))
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "click", "x": 10, "y": 20}
    )

    assert "exclusive control is not active" in result
    assert driver.calls == []


def test_computer_use_routes_desktop_open_app_and_permission(monkeypatch, tmp_path):
    monkeypatch.setattr(
        computer_use_tools.desktop_tools,
        "run_desktop_action",
        lambda params: (_ for _ in ()).throw(AssertionError("legacy desktop runner should not be used")),
    )
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_permission_file", lambda: tmp_path / "permissions.json")

    result = computer_use_tools.computer_use.invoke(
        {
            "mode": "desktop",
            "action": "grant_permission",
            "permission": "open_apps",
            "confirm": True,
        }
    )

    assert result == "Computer use permission granted: open_apps."
    assert computer_use_tools.desktop_tools._runtime_permission_granted("open_apps") is True


def test_computer_use_routes_desktop_permissions_to_legacy_tool(monkeypatch):
    monkeypatch.setattr(
        computer_use_tools.desktop_tools,
        "run_desktop_action",
        lambda params: (_ for _ in ()).throw(AssertionError("legacy desktop runner should not be used")),
    )
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_load_permissions", lambda: {"desktop_control": True})

    result = computer_use_tools.computer_use.invoke({"mode": "desktop", "action": "permissions"})

    assert result == "Computer use permissions: desktop_control=true, open_apps=false, terminal=false."


def test_computer_use_routes_desktop_open_app_from_target(monkeypatch):
    guard = FakeLeaseGuard()
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", guard)
    monkeypatch.setattr(
        computer_use_tools.desktop_tools,
        "run_desktop_action",
        lambda params: (_ for _ in ()).throw(AssertionError("legacy desktop runner should not be used")),
    )

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "open_app", "target": "GitHub Desktop"}
    )

    assert "moved to the native Windows driver" in result
    assert guard.heartbeats == 1


def test_computer_use_routes_desktop_close_and_switch_actions(monkeypatch):
    guard = FakeLeaseGuard()
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", guard)
    monkeypatch.setattr(
        computer_use_tools.desktop_tools,
        "run_desktop_action",
        lambda params: (_ for _ in ()).throw(AssertionError("legacy desktop runner should not be used")),
    )

    close_result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "close_app", "target": "chrome"}
    )
    switch_result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "switch_browser_tab", "tab_action": "previous"}
    )

    assert "moved to the native Windows driver" in close_result
    assert "moved to the native Windows driver" in switch_result
    assert guard.heartbeats == 2


def test_computer_use_routes_browser(monkeypatch):
    calls = []
    monkeypatch.setattr(computer_use_tools, "playwright_run", lambda params: calls.append(params) or "browser-ok")

    result = computer_use_tools.computer_use.invoke(
        {"mode": "browser", "action": "click", "target": "button[name=Go]", "element": "Go"}
    )

    assert result == "browser-ok"
    assert calls == [{"action": "click", "target": "button[name=Go]", "element": "Go"}]


def test_computer_use_routes_workspace_actions(monkeypatch):
    calls = []

    class FakeResult:
        action = "browser.navigate"
        status = "ok"
        message = "workspace-ok"
        data = {"url": "https://example.com"}

    class FakeWorker:
        def run(self, params):
            calls.append(params)
            return FakeResult()

    monkeypatch.setattr(computer_use_tools, "workspace_worker", FakeWorker())

    result = computer_use_tools.computer_use.invoke(
        {"mode": "workspace", "action": "browser.navigate", "url": "https://example.com"}
    )

    assert result == "workspace-ok"
    assert calls == [{"action": "browser.navigate", "url": "https://example.com"}]


def test_computer_use_rejects_invalid_form_json():
    result = computer_use_tools.computer_use.invoke(
        {"mode": "browser", "action": "fill_form", "fields_json": "not-json"}
    )

    assert "fields_json must be valid JSON" in result
