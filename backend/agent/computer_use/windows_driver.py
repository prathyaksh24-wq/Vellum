"""Windows host-laptop computer-use driver."""

from __future__ import annotations

from typing import Any

from agent.computer_use.native_windows.driver import WindowsNativeComputerDriver
from agent.computer_use.operator import OperatorResult


class WindowsComputerDriver:
    """Adapter over the native Windows computer-use driver."""

    def __init__(self, *, native_driver: WindowsNativeComputerDriver | None = None) -> None:
        self.native_driver = native_driver or WindowsNativeComputerDriver()

    def health_check(self) -> dict[str, Any]:
        return self.native_driver.health_check()

    def run_action(self, action: str, **params: Any) -> dict[str, Any]:
        try:
            return self._run_action(action, **params)
        except Exception as exc:
            return {
                "status": "error",
                "backend": self.native_driver.backend,
                "message": str(exc),
                "data": {"action": action, **params},
            }

    def _run_action(self, action: str, **params: Any) -> dict[str, Any]:
        clean_params = {
            key: value
            for key, value in params.items()
            if value is not None and value != ""
        }
        normalized = str(action).strip()

        if normalized == "list_apps":
            return self._to_dict(self.native_driver.list_apps())
        if normalized == "list_windows":
            return self._to_dict(self.native_driver.list_windows())
        if normalized in {"observe", "screenshot"}:
            return self._to_dict(
                self.native_driver.get_window_state(
                    **self._observe_params(normalized, clean_params)
                )
            )
        if normalized == "activate_window":
            return self._to_dict(self.native_driver.activate_window(clean_params["window_id"]))
        if normalized in {"click", "double_click", "right_click"}:
            return self._to_dict(
                self.native_driver.click(**self._click_params(normalized, clean_params))
            )
        if normalized in {"type", "type_text"}:
            return self._to_dict(self.native_driver.type_text(**self._type_params(clean_params)))
        if normalized in {"press_key", "hotkey", "keypress"}:
            return self._to_dict(self.native_driver.press_key(**self._key_params(clean_params)))
        if normalized == "scroll":
            return self._to_dict(self.native_driver.scroll(**self._scroll_params(clean_params)))
        if normalized == "drag":
            return self._to_dict(self.native_driver.drag(**clean_params))

        return {
            "status": "unsupported",
            "message": f"Unsupported native desktop action: {action}",
            "data": {"action": action, **params},
            "backend": self.native_driver.backend,
        }

    def _click_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        click_params = dict(params)
        if action == "double_click":
            click_params.setdefault("click_count", 2)
        elif action == "right_click":
            click_params.setdefault("button", "right")
        return click_params

    def _observe_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        observe_params = dict(params)
        if action == "screenshot":
            observe_params["include_screenshot"] = True
        return observe_params

    def _type_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if "text" not in params and "value" in params:
            params = {**params, "text": params["value"]}
            params.pop("value", None)
        return params

    def _key_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if "key" not in params and "keys" in params:
            keys = params["keys"]
            key = "+".join(str(part) for part in keys) if isinstance(keys, list) else str(keys)
            params = {**params, "key": key}
            params.pop("keys", None)
        return params

    def _scroll_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if "scroll_y" not in params and "amount" in params:
            params = {**params, "scroll_y": params["amount"]}
            params.pop("amount", None)
        return params

    def _to_dict(self, result: OperatorResult | dict[str, Any]) -> dict[str, Any]:
        if isinstance(result, OperatorResult):
            return result.to_dict()
        return dict(result)

