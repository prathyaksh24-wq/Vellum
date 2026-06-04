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
        observation = self._window_observation(
            window,
            include_screenshot=include_screenshot,
            include_text=include_text,
        )
        return OperatorResult("ok", self.backend, "Window state captured.", observation=observation)

    def _window_observation(
        self,
        window: ComputerWindow,
        *,
        include_screenshot: bool = True,
        include_text: bool = True,
    ) -> dict[str, Any]:
        observation: dict[str, Any] = {
            "window": window.to_dict(),
            "accessibility": self.accessibility.get_accessibility_state(
                window.hwnd,
                include_text=include_text,
            ),
        }
        if include_screenshot:
            observation["screenshot"] = self.capture.save_window_screenshot(window.hwnd)
        return observation

    def activate_window(self, window_id: str) -> OperatorResult:
        window = self._activate_or_resolve(window_id)
        return self._after_action(window.id, f"Activated window {window.id}.")

    def open_app(self, app: str) -> OperatorResult:
        window = self.app_launcher.launch_app(app, list_windows=self.windowing.list_windows)
        try:
            window = self.windowing.activate_window(window.id)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to activate launched app window: {window.id}; error={exc}"
            ) from exc
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
        return self._after_action(window, "Click complete.")

    def type_text(self, text: str, window_id: str | None = None) -> OperatorResult:
        window = self._activate_or_resolve(window_id)
        self.input.type_text(text)
        return self._after_action(window, "Text typed.")

    def press_key(self, key: str, window_id: str | None = None) -> OperatorResult:
        window = self._activate_or_resolve(window_id)
        self.input.press_key(key)
        return self._after_action(window, "Key pressed.")

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
        return self._after_action(window, "Scroll complete.")

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
        return self._after_action(window, "Drag complete.")

    def _resolve_window(self, window_id: str | None) -> ComputerWindow:
        if window_id:
            return self.windowing.get_window(window_id)
        return self.windowing.active_window()

    def _activate_or_resolve(self, window_id: str | None) -> ComputerWindow:
        if not window_id:
            return self.windowing.active_window()

        try:
            return self.windowing.activate_window(window_id)
        except Exception as first_activation_error:
            recovery_error: Exception | None = None
            try:
                window = self.windowing.get_window(window_id)
            except Exception as exc:
                recovery_error = exc
                windows = self.windowing.list_windows()
                matching_windows = [window for window in windows if window.id == window_id]
                if not matching_windows:
                    raise RuntimeError(
                        "Activation recovery could not verify target identity; "
                        f"window_id={window_id}; "
                        f"first_error={first_activation_error}; "
                        f"refresh_error={recovery_error}; "
                        f"candidate_count={len(windows)}"
                    ) from exc
                if len(matching_windows) != 1:
                    raise RuntimeError(
                        "Activation recovery is ambiguous; "
                        f"window_id={window_id}; "
                        f"first_error={first_activation_error}; "
                        f"refresh_error={recovery_error}; "
                        f"matching_candidate_count={len(matching_windows)}"
                    ) from exc
                window = matching_windows[0]

            try:
                return self.windowing.activate_window(window.id)
            except Exception as second_activation_error:
                details = (
                    "Failed to activate window after recovery; "
                    f"window_id={window_id}; "
                    f"recovered_window_id={window.id}; "
                    f"first_error={first_activation_error}; "
                    f"second_error={second_activation_error}"
                )
                if recovery_error is not None:
                    details += f"; refresh_error={recovery_error}"
                raise RuntimeError(details) from second_activation_error

    def _after_action(self, window: str | ComputerWindow, message: str) -> OperatorResult:
        if isinstance(window, ComputerWindow):
            observation = self.get_window_state(window.id).observation
        else:
            observation = self.get_window_state(window).observation
        return OperatorResult("ok", self.backend, message, observation=observation)

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
