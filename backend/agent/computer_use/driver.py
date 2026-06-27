"""Computer-use driver interfaces."""

from __future__ import annotations

from typing import Any, Protocol


class ComputerDriver(Protocol):
    def health_check(self) -> dict[str, Any]:
        """Return whether the driver is ready for visible computer control."""

    def run_action(self, action: str, **params: Any) -> dict[str, Any]:
        """Run a normalized desktop action."""

