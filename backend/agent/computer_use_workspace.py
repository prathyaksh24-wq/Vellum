"""Controlled workspace action protocol for computer-use mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import Any, Callable

from agent.mcp.playwright_tools import run_tool as playwright_run


class WorkspaceActionError(ValueError):
    """Raised when a workspace action cannot be executed safely."""


@dataclass(frozen=True)
class WorkspaceActionResult:
    action: str
    status: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


def _default_command_runner(command: str, cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-8000:],
    }


class LocalWorkspaceWorker:
    """First visible workspace worker.

    This is not a VM sandbox. It keeps browser and command actions behind a
    narrow protocol so a stronger worker can replace it later.
    """

    def __init__(
        self,
        *,
        playwright_runner: Callable[[dict[str, Any]], str] = playwright_run,
        command_runner: Callable[[str, Path], dict[str, Any]] = _default_command_runner,
        cwd: Path | None = None,
    ) -> None:
        self.playwright_runner = playwright_runner
        self.command_runner = command_runner
        self.cwd = cwd or Path(__file__).resolve().parents[2]

    def run(self, params: dict[str, Any]) -> WorkspaceActionResult:
        action = _action(params)
        if action == "browser.open":
            return self._browser_open(params)
        if action == "browser.navigate":
            return self._browser_navigate(params)
        if action == "input.click":
            return self._input_click(params)
        if action == "input.type":
            return self._input_type(params)
        if action == "input.scroll":
            return self._input_scroll(params)
        if action == "screen.screenshot":
            return self._screenshot(params)
        if action == "terminal.open":
            return WorkspaceActionResult(
                action,
                "ok",
                "Workspace terminal is available in the Vellum terminal panel.",
            )
        if action == "terminal.run":
            return self._terminal_run(params)
        if action == "session.stop":
            return WorkspaceActionResult(action, "ok", "Workspace stop requested.")
        raise WorkspaceActionError(f"Unsupported workspace action: {action}")

    def _browser_open(self, params: dict[str, Any]) -> WorkspaceActionResult:
        url = str(params.get("url") or "about:blank").strip()
        message = self.playwright_runner({"action": "tabs", "tab_action": "new", "url": url})
        return WorkspaceActionResult("browser.open", "ok", message, {"url": url})

    def _browser_navigate(self, params: dict[str, Any]) -> WorkspaceActionResult:
        url = _required(params, "url", "browser.navigate requires url")
        message = self.playwright_runner({"action": "navigate", "url": url})
        return WorkspaceActionResult("browser.navigate", "ok", message, {"url": url})

    def _input_click(self, params: dict[str, Any]) -> WorkspaceActionResult:
        target = _required(params, "target", "input.click requires target")
        call = {"action": "click", "target": target}
        if params.get("element"):
            call["element"] = str(params["element"])
        message = self.playwright_runner(call)
        return WorkspaceActionResult("input.click", "ok", message, {"target": target})

    def _input_type(self, params: dict[str, Any]) -> WorkspaceActionResult:
        target = _required(params, "target", "input.type requires target")
        text = _required(params, "text", "input.type requires text")
        call: dict[str, Any] = {"action": "type", "target": target, "text": text}
        if params.get("element"):
            call["element"] = str(params["element"])
        if params.get("submit") is not None:
            call["submit"] = bool(params["submit"])
        message = self.playwright_runner(call)
        return WorkspaceActionResult("input.type", "ok", message, {"target": target, "text": "[redacted]"})

    def _input_scroll(self, params: dict[str, Any]) -> WorkspaceActionResult:
        amount = int(params.get("amount") or 1)
        key = "PageDown" if amount >= 0 else "PageUp"
        for _ in range(max(1, abs(amount))):
            self.playwright_runner({"action": "press_key", "key": key})
        return WorkspaceActionResult("input.scroll", "ok", f"Workspace scrolled with {key}.", {"amount": amount})

    def _screenshot(self, params: dict[str, Any]) -> WorkspaceActionResult:
        filename = str(params.get("filename") or "workspace.png")
        message = self.playwright_runner({"action": "screenshot", "filename": filename, "full_page": True})
        return WorkspaceActionResult("screen.screenshot", "ok", message, {"filename": filename})

    def _terminal_run(self, params: dict[str, Any]) -> WorkspaceActionResult:
        command = _required(params, "command", "terminal.run requires command")
        result = self.command_runner(command, self.cwd)
        status = "ok" if result.get("returncode") == 0 else "error"
        return WorkspaceActionResult(
            "terminal.run",
            status,
            f"Workspace command exited with {result.get('returncode')}.",
            result,
        )


def _action(params: dict[str, Any]) -> str:
    return str(params.get("action") or "").strip().casefold().replace("_", ".")


def _required(params: dict[str, Any], key: str, message: str) -> str:
    value = str(params.get(key) or "").strip()
    if not value:
        raise WorkspaceActionError(message)
    return value


workspace_worker = LocalWorkspaceWorker()
