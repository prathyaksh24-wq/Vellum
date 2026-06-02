from __future__ import annotations

from typing import Any

from agent.computer_use.native_windows import accessibility as default_accessibility
from agent.computer_use.native_windows import app_launch as default_app_launch
from agent.computer_use.native_windows import capture as default_capture
from agent.computer_use.native_windows import input as default_input
from agent.computer_use.native_windows import windowing as default_windowing
from agent.computer_use.operator import ComputerWindow, OperatorResult


class WindowsNativeComputerDriver:
    backend = "windows_native"

    def __init__(
        self,
        *,
        windowing=default_windowing,
        accessibility=default_accessibility,
        capture=default_capture,
        input_layer=default_input,
        app_launcher=default_app_launch,
    ) -> None:
        self.windowing = windowing
        self.accessibility = accessibility
        self.capture = capture
        self.input = input_layer
        self.app_launcher = app_launcher

    def health_check(self) -> dict[str, Any]:
        try:
            windows = self.windowing.list_windows()
        except Exception as exc:
            return {"ok": False, "backend": self.backend, "message": str(exc)}
        return {
            "ok": True,
            "backend": self.backend,
            "message": f"{len(windows)} targetable windows found.",
        }

    def list_apps(self) -> OperatorResult:
        apps = sorted({window.app for window in self.windowing.list_windows() if window.app})
        return OperatorResult("ok", self.backend, f"{len(apps)} apps found.", {"apps": apps})

    def list_windows(self) -> OperatorResult:
        windows = self.windowing.list_windows()
        return OperatorResult(
            "ok",
            self.backend,
            f"{len(windows)} windows found.",
            {"windows": [window.to_dict() for window in windows]},
        )

    def get_window_state(
        self,
        window_id: str | None = None,
        *,
        include_screenshot: bool = True,
        include_text: bool = True,
    ) -> OperatorResult:
        window = self._resolve_window(window_id)
        observation: dict[str, Any] = {
            "window": window.to_dict(),
            "accessibility": self.accessibility.get_accessibility_state(
                window.hwnd,
                include_text=include_text,
            ),
        }
        if include_screenshot:
            observation["screenshot"] = self.capture.save_window_screenshot(window.hwnd)
        return OperatorResult("ok", self.backend, "Window state captured.", observation=observation)

    def activate_window(self, window_id: str) -> OperatorResult:
        window = self.windowing.activate_window(window_id)
        return self._after_action(window.id, f"Activated window {window.id}.")

    def open_app(self, app: str) -> OperatorResult:
        window = self.app_launcher.launch_app(app, list_windows=self.windowing.list_windows)
        try:
            window = self.windowing.activate_window(window.id)
        except Exception:
            window = self.windowing.get_window(window.id)
        result = self.get_window_state(window.id)
        return OperatorResult(
            "ok",
            self.backend,
            f"Opened app {app}.",
            observation=result.observation,
        )

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
        window = self._activate_or_resolve(window_id)
        if element_index is not None:
            state = self.accessibility.get_accessibility_state(window.hwnd, include_text=True)
            x, y = self.accessibility.element_center(state, element_index)
        else:
            x, y = self._to_screen_point(window, int(x), int(y)) if x is not None and y is not None else (x, y)
        if x is None or y is None:
            raise ValueError("click requires element_index or x/y coordinates.")
        self.input.click(int(x), int(y), button=button, click_count=click_count)
        return self._after_action(window.id, "Click complete.")

    def type_text(self, text: str, window_id: str | None = None) -> OperatorResult:
        window = self._activate_or_resolve(window_id)
        self.input.type_text(text)
        return self._after_action(window.id, "Text typed.")

    def press_key(self, key: str, window_id: str | None = None) -> OperatorResult:
        window = self._activate_or_resolve(window_id)
        self.input.press_key(key)
        return self._after_action(window.id, "Key pressed.")

    def scroll(
        self,
        window_id: str | None = None,
        *,
        x: int | None = None,
        y: int | None = None,
        scroll_x: int = 0,
        scroll_y: int = 0,
    ) -> OperatorResult:
        window = self._activate_or_resolve(window_id)
        if x is None or y is None:
            x, y = self._window_center(window)
        else:
            x, y = self._to_screen_point(window, int(x), int(y))
        self.input.scroll(int(x), int(y), scroll_x=scroll_x, scroll_y=scroll_y)
        return self._after_action(window.id, "Scroll complete.")

    def drag(
        self,
        window_id: str | None = None,
        *,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
    ) -> OperatorResult:
        window = self._activate_or_resolve(window_id)
        from_x, from_y = self._to_screen_point(window, from_x, from_y)
        to_x, to_y = self._to_screen_point(window, to_x, to_y)
        self.input.drag(int(from_x), int(from_y), int(to_x), int(to_y))
        return self._after_action(window.id, "Drag complete.")

    def _resolve_window(self, window_id: str | None) -> ComputerWindow:
        if window_id:
            return self.windowing.get_window(window_id)
        return self.windowing.active_window()

    def _activate_or_resolve(self, window_id: str | None) -> ComputerWindow:
        if window_id:
            return self.windowing.activate_window(window_id)
        return self.windowing.active_window()

    def _after_action(self, window_id: str, message: str) -> OperatorResult:
        result = self.get_window_state(window_id)
        return OperatorResult("ok", self.backend, message, observation=result.observation)

    def _window_origin(self, window: ComputerWindow) -> tuple[int, int]:
        bounds = window.bounds
        return int(bounds.get("x", 0)), int(bounds.get("y", 0))

    def _window_center(self, window: ComputerWindow) -> tuple[int, int]:
        bounds = window.bounds
        origin_x, origin_y = self._window_origin(window)
        return (
            origin_x + int(bounds.get("width", 0)) // 2,
            origin_y + int(bounds.get("height", 0)) // 2,
        )

    def _to_screen_point(self, window: ComputerWindow, x: int, y: int) -> tuple[int, int]:
        origin_x, origin_y = self._window_origin(window)
        return origin_x + int(x), origin_y + int(y)
