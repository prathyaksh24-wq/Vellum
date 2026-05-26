from pathlib import Path

import pytest

from agent.tools import desktop as desktop_tools
from agent.tools import computer_use as computer_use_tools


class FakeScreenshot:
    def __init__(self, owner):
        self.owner = owner

    def save(self, path):
        self.owner.screenshot_saved_to = Path(path)


class FakePyAutoGui:
    FAILSAFE = False
    PAUSE = 0

    def __init__(self):
        self.calls = []
        self.screenshot_saved_to = None

    def screenshot(self):
        self.calls.append(("screenshot",))
        return FakeScreenshot(self)

    def position(self):
        return (12, 34)

    def size(self):
        return (1920, 1080)

    def click(self, x=None, y=None, button="left", clicks=1):
        self.calls.append(("click", x, y, button, clicks))

    def moveTo(self, x, y, duration=0):
        self.calls.append(("moveTo", x, y, duration))

    def dragTo(self, x, y, duration=0, button="left"):
        self.calls.append(("dragTo", x, y, duration, button))

    def scroll(self, clicks):
        self.calls.append(("scroll", clicks))

    def write(self, text, interval=0):
        self.calls.append(("write", text, interval))

    def press(self, key):
        self.calls.append(("press", key))

    def hotkey(self, *keys):
        self.calls.append(("hotkey", keys))


def test_desktop_screenshot_saves_file(monkeypatch, tmp_path):
    fake = FakePyAutoGui()
    monkeypatch.setattr(desktop_tools, "_pyautogui", lambda: fake)
    monkeypatch.setattr(desktop_tools, "_screenshot_dir", lambda: tmp_path)

    result = desktop_tools.run_desktop_action({"action": "screenshot", "filename": "screen.png"})

    assert "screen.png" in result
    assert fake.screenshot_saved_to == tmp_path / "screen.png"


def test_desktop_click_requires_gate(monkeypatch):
    monkeypatch.setattr(desktop_tools, "_desktop_allowed", lambda: False)

    result = desktop_tools.run_desktop_action({"action": "click", "x": 10, "y": 20})

    assert "requires COMPUTER_USE_ALLOW_DESKTOP=true" in result


def test_desktop_click_when_enabled(monkeypatch):
    fake = FakePyAutoGui()
    monkeypatch.setattr(desktop_tools, "_pyautogui", lambda: fake)
    monkeypatch.setattr(desktop_tools, "_desktop_allowed", lambda: True)
    monkeypatch.setattr(desktop_tools, "_runtime_permission_granted", lambda permission: True)

    result = desktop_tools.run_desktop_action({"action": "click", "x": 10, "y": 20, "button": "left"})

    assert result == "Desktop click completed at 10,20."
    assert fake.calls == [("click", 10, 20, "left", 1)]


def test_desktop_hotkey_when_enabled(monkeypatch):
    fake = FakePyAutoGui()
    monkeypatch.setattr(desktop_tools, "_pyautogui", lambda: fake)
    monkeypatch.setattr(desktop_tools, "_desktop_allowed", lambda: True)
    monkeypatch.setattr(desktop_tools, "_runtime_permission_granted", lambda permission: True)

    result = desktop_tools.run_desktop_action({"action": "hotkey", "keys": "ctrl,l"})

    assert result == "Desktop hotkey completed: ctrl+l."
    assert fake.calls == [("hotkey", ("ctrl", "l"))]


def test_desktop_terminal_command_uses_visible_launcher_when_enabled(monkeypatch):
    launched = []
    monkeypatch.setattr(desktop_tools, "_desktop_allowed", lambda: True)
    monkeypatch.setattr(desktop_tools, "_runtime_permission_granted", lambda permission: True)
    monkeypatch.setattr(
        desktop_tools,
        "_launch_terminal_command",
        lambda command, shell="powershell": launched.append((command, shell, True)),
    )

    result = desktop_tools.run_desktop_action(
        {"action": "run_terminal_command", "command": "codex", "shell": "powershell"}
    )

    assert "Visible terminal command started" in result
    assert launched == [("codex", "powershell", True)]


def test_desktop_terminal_command_requires_gate(monkeypatch):
    monkeypatch.setattr(desktop_tools, "_desktop_allowed", lambda: False)

    result = desktop_tools.run_desktop_action({"action": "run_terminal_command", "command": "codex"})

    assert "requires COMPUTER_USE_ALLOW_DESKTOP=true" in result


def test_desktop_mutating_action_wraps_orange_activity_overlay(monkeypatch):
    fake = FakePyAutoGui()
    events = []

    class FakeOverlay:
        def __enter__(self):
            events.append("start")

        def __exit__(self, exc_type, exc, tb):
            events.append("stop")

    monkeypatch.setattr(desktop_tools, "_pyautogui", lambda: fake)
    monkeypatch.setattr(desktop_tools, "_desktop_allowed", lambda: True)
    monkeypatch.setattr(desktop_tools, "_runtime_permission_granted", lambda permission: True)
    monkeypatch.setattr(desktop_tools, "_activity_overlay", lambda: FakeOverlay(), raising=False)

    result = desktop_tools.run_desktop_action({"action": "type", "text": "codex"})

    assert result == "Desktop type completed."
    assert events == ["start", "stop"]
    assert fake.calls == [("write", "codex", 0)]


def test_desktop_open_app_uses_visible_app_launcher_when_granted(monkeypatch):
    launched = []
    monkeypatch.setattr(desktop_tools, "_desktop_allowed", lambda: True)
    monkeypatch.setattr(desktop_tools, "_runtime_permission_granted", lambda permission: True)
    monkeypatch.setattr(desktop_tools, "_launch_app", lambda app: launched.append(app))

    result = desktop_tools.run_desktop_action({"action": "open_app", "app": "Terminal"})

    assert result == "Desktop app launch requested: Terminal."
    assert launched == ["Terminal"]


def test_desktop_open_app_requests_runtime_permission(monkeypatch):
    monkeypatch.setattr(desktop_tools, "_desktop_allowed", lambda: True)
    monkeypatch.setattr(desktop_tools, "_runtime_permission_granted", lambda permission: False)

    result = desktop_tools.run_desktop_action({"action": "open_app", "app": "Terminal"})

    assert "Computer use permission required: open_apps" in result
    assert "grant_permission" in result


def test_desktop_grant_permission_persists_runtime_grant(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop_tools, "_permission_file", lambda: tmp_path / "permissions.json")

    result = desktop_tools.run_desktop_action(
        {"action": "grant_permission", "permission": "open_apps", "confirm": True}
    )

    assert result == "Computer use permission granted: open_apps."
    assert desktop_tools._runtime_permission_granted("open_apps") is True


def test_computer_use_routes_desktop(monkeypatch):
    calls = []
    monkeypatch.setattr(
        computer_use_tools.desktop_tools,
        "run_desktop_action",
        lambda params: calls.append(params) or "desktop-ok",
    )

    result = computer_use_tools.computer_use.invoke({"mode": "desktop", "action": "position"})

    assert result == "desktop-ok"
    assert calls == [{"action": "position"}]


def test_computer_use_routes_desktop_terminal_command(monkeypatch):
    calls = []
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(
        computer_use_tools.desktop_tools,
        "run_desktop_action",
        lambda params: calls.append(params) or "terminal-ok",
    )

    result = computer_use_tools.computer_use.invoke(
        {
            "mode": "desktop",
            "action": "run_terminal_command",
            "command": "claude",
            "shell": "powershell",
        }
    )

    assert result == "terminal-ok"
    assert calls == [{"action": "run_terminal_command", "command": "claude", "shell": "powershell"}]


def test_computer_use_blocks_desktop_mutation_when_mode_disabled(monkeypatch):
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: False)

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "click", "x": 10, "y": 20}
    )

    assert "Computer use mode is disabled" in result
    assert "enable computer use" in result


def test_computer_use_routes_desktop_open_app_and_permission(monkeypatch):
    calls = []
    monkeypatch.setattr(
        computer_use_tools.desktop_tools,
        "run_desktop_action",
        lambda params: calls.append(params) or "app-ok",
    )

    result = computer_use_tools.computer_use.invoke(
        {
            "mode": "desktop",
            "action": "grant_permission",
            "permission": "open_apps",
            "confirm": True,
        }
    )

    assert result == "app-ok"
    assert calls == [{"action": "grant_permission", "permission": "open_apps", "confirm": True}]


def test_computer_use_routes_desktop_open_app_from_target(monkeypatch):
    calls = []
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(
        computer_use_tools.desktop_tools,
        "run_desktop_action",
        lambda params: calls.append(params) or "app-ok",
    )

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "open_app", "target": "GitHub Desktop"}
    )

    assert result == "app-ok"
    assert calls == [{"action": "open_app", "app": "GitHub Desktop"}]


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
