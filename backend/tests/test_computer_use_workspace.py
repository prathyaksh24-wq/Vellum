from pathlib import Path

import pytest

from agent.computer_use_workspace import LocalWorkspaceWorker, WorkspaceActionError


class FakePlaywright:
    def __init__(self):
        self.calls = []

    def __call__(self, params):
        self.calls.append(params)
        return f"browser:{params['action']}"


class FakeCommandRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, cwd):
        self.calls.append((command, cwd))
        return {"returncode": 0, "stdout": "ok", "stderr": ""}


def test_workspace_maps_browser_actions_to_playwright(tmp_path: Path):
    browser = FakePlaywright()
    worker = LocalWorkspaceWorker(
        playwright_runner=browser,
        command_runner=FakeCommandRunner(),
        cwd=tmp_path,
    )

    result = worker.run({"action": "browser.navigate", "url": "https://example.com"})

    assert result.status == "ok"
    assert result.action == "browser.navigate"
    assert browser.calls == [{"action": "navigate", "url": "https://example.com"}]
    assert "browser:navigate" in result.message


def test_workspace_maps_click_type_scroll_and_screenshot(tmp_path: Path):
    browser = FakePlaywright()
    worker = LocalWorkspaceWorker(
        playwright_runner=browser,
        command_runner=FakeCommandRunner(),
        cwd=tmp_path,
    )

    worker.run({"action": "input.click", "target": "button[name=Search]", "element": "Search"})
    worker.run({"action": "input.type", "target": "input[name=q]", "text": "vellum", "submit": True})
    worker.run({"action": "input.scroll", "amount": 2})
    worker.run({"action": "screen.screenshot", "filename": "workspace.png"})

    assert browser.calls == [
        {"action": "click", "target": "button[name=Search]", "element": "Search"},
        {"action": "type", "target": "input[name=q]", "text": "vellum", "submit": True},
        {"action": "press_key", "key": "PageDown"},
        {"action": "press_key", "key": "PageDown"},
        {"action": "screenshot", "filename": "workspace.png", "full_page": True},
    ]


def test_workspace_terminal_run_uses_controlled_cwd(tmp_path: Path):
    commands = FakeCommandRunner()
    worker = LocalWorkspaceWorker(
        playwright_runner=FakePlaywright(),
        command_runner=commands,
        cwd=tmp_path,
    )

    result = worker.run({"action": "terminal.run", "command": "echo hello"})

    assert result.status == "ok"
    assert commands.calls == [("echo hello", tmp_path)]
    assert result.data["returncode"] == 0
    assert result.data["stdout"] == "ok"


def test_workspace_rejects_unknown_or_missing_inputs(tmp_path: Path):
    worker = LocalWorkspaceWorker(
        playwright_runner=FakePlaywright(),
        command_runner=FakeCommandRunner(),
        cwd=tmp_path,
    )

    with pytest.raises(WorkspaceActionError, match="requires url"):
        worker.run({"action": "browser.navigate"})

    with pytest.raises(WorkspaceActionError, match="Unsupported workspace action"):
        worker.run({"action": "host.delete_files"})
