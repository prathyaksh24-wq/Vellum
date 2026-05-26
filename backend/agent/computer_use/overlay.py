"""Computer-use activity overlay adapters."""

from __future__ import annotations

from typing import Any

from agent.tools import desktop as desktop_tools


class DesktopActivityOverlay:
    """Backend fallback overlay controller.

    The Tauri shell is expected to own the primary full-screen overlay when it
    is available. This adapter keeps API/session behavior deterministic for
    backend tests and non-Tauri development.
    """

    def start(self) -> str:
        return desktop_tools.start_activity_overlay()

    def stop(self) -> str:
        return desktop_tools.stop_activity_overlay()

    def status(self) -> dict[str, Any]:
        return {"ready": True, "controller": "backend"}
