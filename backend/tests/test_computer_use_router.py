from __future__ import annotations

from agent.computer_use.router import ComputerUseActionRouter


class FakeDesktopDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def run_action(self, action: str, **params):
        self.calls.append((action, params))
        result = {"status": "ok", "backend": "windows_native", "message": f"desktop {action}", "data": params}
        if action == "screenshot":
            result["observation"] = {"window": {"id": "hwnd:1"}, "screenshot": {"path": "screen.png"}}
        return result


class FakeObservedDesktopDriver(FakeDesktopDriver):
    def run_action(self, action: str, **params):
        self.calls.append((action, params))
        return {
            "status": "ok",
            "backend": "windows_native",
            "message": f"desktop {action}",
            "data": params,
            "observation": {"window": {"id": "hwnd:1"}, "screenshot": {"path": "native.png"}},
        }


def test_router_sends_host_actions_to_desktop_driver():
    desktop = FakeDesktopDriver()
    router = ComputerUseActionRouter(desktop_driver=desktop, browser_runner=lambda params: "browser")

    result = router.run_action({"type": "list_windows"})

    assert result["status"] == "ok"
    assert desktop.calls == [("list_windows", {})]


def test_router_sends_browser_actions_to_playwright():
    calls = []
    router = ComputerUseActionRouter(
        desktop_driver=FakeDesktopDriver(),
        browser_runner=lambda params: calls.append(params) or "browser ok",
    )

    result = router.run_action({"type": "browser_open", "url": "https://example.com"})

    assert result["status"] == "ok"
    assert result["message"] == "browser ok"
    assert calls == [{"action": "tabs", "tab_action": "new", "url": "https://example.com"}]


def test_router_records_screenshot_after_mutating_desktop_action():
    desktop = FakeDesktopDriver()
    router = ComputerUseActionRouter(desktop_driver=desktop, browser_runner=lambda params: "browser")

    result = router.run_action({"type": "click", "x": 10, "y": 20})

    assert result["status"] == "ok"
    assert desktop.calls == [
        ("click", {"x": 10, "y": 20}),
        ("screenshot", {}),
    ]
    assert result["observation"]["message"] == "desktop screenshot"
    assert result["observation"]["observation"]["screenshot"]["path"] == "screen.png"


def test_router_preserves_existing_mutating_action_observation_without_nesting():
    desktop = FakeObservedDesktopDriver()
    router = ComputerUseActionRouter(desktop_driver=desktop, browser_runner=lambda params: "browser")

    result = router.run_action({"type": "click", "x": 10, "y": 20})

    assert result["status"] == "ok"
    assert desktop.calls == [("click", {"x": 10, "y": 20})]
    assert result["observation"]["screenshot"]["path"] == "native.png"
    assert "observation" not in result["observation"]


def test_router_run_instruction_queues_visible_task():
    desktop = FakeDesktopDriver()
    router = ComputerUseActionRouter(desktop_driver=desktop, browser_runner=lambda params: "browser")

    result = router.run_instruction("open notepad", session_id="session-1")

    assert result["status"] == "queued"
    assert result["session_id"] == "session-1"
    assert result["steps"][0]["type"] == "screenshot"
