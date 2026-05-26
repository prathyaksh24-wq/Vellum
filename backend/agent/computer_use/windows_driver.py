"""Windows host-laptop computer-use driver."""

from __future__ import annotations

from typing import Any

from agent.tools import desktop as desktop_tools


class WindowsComputerDriver:
    """Adapter over the existing desktop tools with structured results."""

    def health_check(self) -> dict[str, Any]:
        try:
            result = desktop_tools.run_desktop_action({"action": "screen_size"})
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        ok = "screen size" in result.casefold()
        return {"ok": ok, "message": result}

    def run_action(self, action: str, **params: Any) -> dict[str, Any]:
        payload = {"action": action}
        payload.update({key: value for key, value in params.items() if value is not None and value != ""})
        result = desktop_tools.run_desktop_action(payload)
        return {"status": "ok", "message": result, "data": {"action": action, **params}}

