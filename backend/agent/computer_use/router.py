"""Routes normalized computer-use actions to desktop and browser drivers."""

from __future__ import annotations

from typing import Any, Callable

from agent.computer_use.driver import ComputerDriver
from agent.computer_use.windows_driver import WindowsComputerDriver
from agent.mcp.playwright_tools import run_tool as playwright_run


MUTATING_DESKTOP_ACTIONS = {
    "click",
    "double_click",
    "right_click",
    "move",
    "drag",
    "scroll",
    "type",
    "keypress",
    "press_key",
    "hotkey",
    "open_app",
    "close_app",
    "close_window",
    "open_terminal",
    "run_terminal",
    "run_terminal_command",
    "switch_app",
    "switch_browser_tab",
    "close_browser_tab",
}


class ComputerUseActionRouter:
    """Small action router used by session orchestration and tests."""

    def __init__(
        self,
        *,
        desktop_driver: ComputerDriver | None = None,
        browser_runner: Callable[[dict[str, Any]], str] = playwright_run,
    ) -> None:
        self.desktop_driver = desktop_driver or WindowsComputerDriver()
        self.browser_runner = browser_runner

    def run_instruction(self, instruction: str, *, session_id: str) -> dict[str, object]:
        observation = self.desktop_driver.run_action("screenshot")
        return {
            "status": "queued",
            "session_id": session_id,
            "steps": [
                {"type": "screenshot", "message": observation["message"], "data": observation.get("data", {})},
                {"type": "action", "message": f"Instruction queued for agent loop: {instruction}"},
            ],
        }

    def run_action(self, action: dict[str, Any]) -> dict[str, Any]:
        action_type = str(action.get("type") or action.get("action") or "").strip()
        if not action_type:
            raise ValueError("Computer-use action requires type.")
        if action_type.startswith("browser_"):
            return self._run_browser_action(action_type, action)
        result = self._run_desktop_action(action_type, action)
        if action_type in MUTATING_DESKTOP_ACTIONS and "observation" not in result:
            result["observation"] = self.desktop_driver.run_action("screenshot")
        return result

    def _run_desktop_action(self, action_type: str, action: dict[str, Any]) -> dict[str, Any]:
        mapped = {
            "type": "type",
            "keypress": "press_key",
            "run_terminal": "run_terminal_command",
        }.get(action_type, action_type)
        params = {key: value for key, value in action.items() if key not in {"type", "action"}}
        return self.desktop_driver.run_action(mapped, **params)

    def _run_browser_action(self, action_type: str, action: dict[str, Any]) -> dict[str, Any]:
        if action_type == "browser_open":
            params = {"action": "tabs", "tab_action": "new", "url": action.get("url") or "about:blank"}
        elif action_type == "browser_tabs":
            params = {
                "action": "tabs",
                "tab_action": action.get("tab_action") or action.get("tabs_action") or "list",
            }
            if action.get("url"):
                params["url"] = action["url"]
            if action.get("index") is not None:
                params["index"] = action["index"]
        else:
            params = {"action": action_type.removeprefix("browser_")}
            params.update({key: value for key, value in action.items() if key not in {"type", "action"}})
        message = self.browser_runner(params)
        return {"status": "ok", "message": message, "data": params}


computer_use_action_router = ComputerUseActionRouter()
