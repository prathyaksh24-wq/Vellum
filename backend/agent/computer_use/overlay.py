"""Computer-use activity overlay adapters."""

from __future__ import annotations

from typing import Any

from agent.computer_use.native_windows.overlay import NativeWindowsOverlayController


class DesktopActivityOverlay:
    """Backend overlay controller backed by the native Windows overlay."""

    def __init__(self) -> None:
        self._controller = NativeWindowsOverlayController()

    def set_interrupt_callback(self, callback) -> None:
        self._controller.set_interrupt_callback(callback)

    def start(self) -> str:
        return self._controller.start()

    def stop(self) -> str:
        return self._controller.stop()

    def status(self) -> dict[str, Any]:
        return self._controller.status()
