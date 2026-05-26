from __future__ import annotations

from agent.computer_use.windows_driver import WindowsComputerDriver


def test_windows_driver_delegates_structured_actions(monkeypatch):
    calls = []

    def fake_run(params):
        calls.append(params)
        return "Desktop action complete."

    monkeypatch.setattr("agent.computer_use.windows_driver.desktop_tools.run_desktop_action", fake_run)
    driver = WindowsComputerDriver()

    result = driver.run_action("open_app", app="notepad")

    assert calls == [{"action": "open_app", "app": "notepad"}]
    assert result == {
        "status": "ok",
        "message": "Desktop action complete.",
        "data": {"action": "open_app", "app": "notepad"},
    }


def test_windows_driver_health_check_reports_unavailable(monkeypatch):
    monkeypatch.setattr("agent.computer_use.windows_driver.desktop_tools.run_desktop_action", lambda params: "nope")
    driver = WindowsComputerDriver()

    result = driver.health_check()

    assert result["ok"] is False
