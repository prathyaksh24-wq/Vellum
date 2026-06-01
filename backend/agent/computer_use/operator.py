from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ComputerWindow:
    id: str
    hwnd: int
    app: str
    pid: int
    title: str
    bounds: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "hwnd": self.hwnd,
            "app": self.app,
            "pid": self.pid,
            "title": self.title,
            "bounds": dict(self.bounds),
        }


@dataclass(frozen=True)
class OperatorResult:
    status: str
    backend: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    observation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "backend": self.backend,
            "message": self.message,
            "data": dict(self.data),
        }
        if self.observation is not None:
            payload["observation"] = self.observation
        return payload


class ComputerOperator(Protocol):
    def health_check(self) -> dict[str, Any]: ...

    def list_apps(self) -> OperatorResult: ...

    def list_windows(self) -> OperatorResult: ...

    def get_window_state(
        self,
        window_id: str | None = None,
        *,
        include_screenshot: bool = True,
        include_text: bool = True,
    ) -> OperatorResult: ...

    def activate_window(self, window_id: str) -> OperatorResult: ...

    def click(
        self,
        window_id: str | None = None,
        *,
        element_index: int | None = None,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        click_count: int = 1,
    ) -> OperatorResult: ...

    def type_text(self, text: str, window_id: str | None = None) -> OperatorResult: ...

    def press_key(self, key: str, window_id: str | None = None) -> OperatorResult: ...

    def scroll(
        self,
        window_id: str | None = None,
        *,
        x: int = 0,
        y: int = 0,
        scroll_x: int = 0,
        scroll_y: int = 0,
    ) -> OperatorResult: ...

    def drag(
        self,
        window_id: str | None = None,
        *,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
    ) -> OperatorResult: ...


class CodexComputerUseAdapter:
    backend = "codex_fallback"

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": False,
            "backend": self.backend,
            "message": "Codex Computer Use fallback is unavailable.",
        }

    def _unavailable(self, action: str) -> OperatorResult:
        return OperatorResult(
            status="unavailable",
            backend=self.backend,
            message=f"Codex Computer Use fallback is unavailable for {action}.",
            data={"action": action},
        )

    def list_apps(self) -> OperatorResult:
        return self._unavailable("list_apps")

    def list_windows(self) -> OperatorResult:
        return self._unavailable("list_windows")

    def get_window_state(
        self,
        window_id: str | None = None,
        *,
        include_screenshot: bool = True,
        include_text: bool = True,
    ) -> OperatorResult:
        return self._unavailable("get_window_state")

    def activate_window(self, window_id: str) -> OperatorResult:
        return self._unavailable("activate_window")

    def click(
        self,
        window_id: str | None = None,
        *,
        element_index: int | None = None,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        click_count: int = 1,
    ) -> OperatorResult:
        return self._unavailable("click")

    def type_text(self, text: str, window_id: str | None = None) -> OperatorResult:
        return self._unavailable("type_text")

    def press_key(self, key: str, window_id: str | None = None) -> OperatorResult:
        return self._unavailable("press_key")

    def scroll(
        self,
        window_id: str | None = None,
        *,
        x: int = 0,
        y: int = 0,
        scroll_x: int = 0,
        scroll_y: int = 0,
    ) -> OperatorResult:
        return self._unavailable("scroll")

    def drag(
        self,
        window_id: str | None = None,
        *,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
    ) -> OperatorResult:
        return self._unavailable("drag")
