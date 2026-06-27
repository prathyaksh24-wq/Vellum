# Native Computer Use Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Vellum native Windows computer use reliably launch and control Notepad and Brave, while fixing the input guard warning and polishing the blue takeover overlay.

**Architecture:** Keep the existing `computer_use(mode="desktop") -> WindowsComputerDriver -> WindowsNativeComputerDriver` path. Add native app launch and activation recovery at the native-driver boundary, keep permission checks in `agent.tools.computer_use`, and replace the overlay border implementation without changing the session API.

**Tech Stack:** Python 3.13, pytest, ctypes/Win32 APIs, subprocess, psutil, Tkinter, Pillow.

---

## File Structure

- Modify `backend/agent/tools/computer_use.py`: route `open_app` and `launch_app` into the native desktop driver and keep `open_apps` permission enforcement.
- Modify `backend/agent/computer_use/windows_driver.py`: delegate `open_app` and `launch_app` actions to `WindowsNativeComputerDriver.open_app`.
- Create `backend/agent/computer_use/native_windows/app_launch.py`: resolve app aliases, launch executables, and poll for target windows.
- Modify `backend/agent/computer_use/native_windows/driver.py`: add `open_app`, activation recovery, and structured errors from recovered windows.
- Modify `backend/agent/computer_use/input_guard.py`: fix low-level hook callback signatures and `CallNextHookEx` argtypes/restype.
- Modify `backend/agent/computer_use/native_windows/overlay.py`: replace stacked rectangle edge rendering with one Pillow-backed soft glow image and a lower status pill.
- Modify `backend/tests/test_computer_use.py`: assert `open_app` routes to native driver after permission.
- Modify `backend/tests/test_computer_use_driver.py`: assert adapter delegates `open_app` / `launch_app`.
- Modify `backend/tests/test_native_driver.py`: assert native `open_app` launches and activation recovers.
- Create `backend/tests/test_native_app_launch.py`: unit test alias resolution and polling.
- Create `backend/tests/test_input_guard.py`: test pointer-safe Win32 hook signatures.
- Modify `backend/tests/test_computer_use_session.py` and `backend/tests/test_native_overlay.py`: update overlay design expectations.

---

## Task 1: Route Native App Launch Through Public Computer Use

**Files:**
- Modify: `backend/agent/tools/computer_use.py`
- Modify: `backend/agent/computer_use/windows_driver.py`
- Modify: `backend/tests/test_computer_use.py`
- Modify: `backend/tests/test_computer_use_driver.py`

- [ ] **Step 1: Update public routing tests first**

In `backend/tests/test_computer_use.py`, replace `test_computer_use_routes_desktop_open_app_from_target` with:

```python
def test_computer_use_routes_desktop_open_app_from_target(monkeypatch):
    driver = FakeDesktopDriver("Opened app brave.")
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", FakeLeaseGuard())
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_runtime_permission_granted", lambda permission: permission == "open_apps")
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_desktop_allowed", lambda: True)

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "open_app", "target": "brave"}
    )

    assert result == "Opened app brave."
    assert driver.calls == [("open_app", {"app": "brave"})]
```

Add this test below it:

```python
def test_computer_use_routes_desktop_launch_app_alias(monkeypatch):
    driver = FakeDesktopDriver("Opened app notepad.")
    monkeypatch.setattr(computer_use_tools.computer_use_runtime, "is_enabled", lambda: True)
    monkeypatch.setattr(computer_use_tools, "computer_use_input_guard", FakeLeaseGuard())
    monkeypatch.setattr(computer_use_tools, "desktop_driver", driver)
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_runtime_permission_granted", lambda permission: permission == "open_apps")
    monkeypatch.setattr(computer_use_tools.desktop_tools, "_desktop_allowed", lambda: True)

    result = computer_use_tools.computer_use.invoke(
        {"mode": "desktop", "action": "launch_app", "app": "notepad"}
    )

    assert result == "Opened app notepad."
    assert driver.calls == [("launch_app", {"app": "notepad"})]
```

In the same file, add `"app"` to `FakeDesktopDriver.run_action` `allowed_params`:

```python
        allowed_params = {
            "amount",
            "app",
            "button",
            "click_count",
            "duration",
            "element_index",
            "filename",
            "from_x",
            "from_y",
            "include_screenshot",
            "interval",
            "key",
            "keys",
            "scroll_y",
            "shell",
            "text",
            "to_x",
            "to_y",
            "window_id",
            "x",
            "y",
        }
```

- [ ] **Step 2: Update adapter tests first**

In `backend/tests/test_computer_use_driver.py`, add `open_app` to `FakeNativeDriver`:

```python
    def open_app(self, **params):
        self.calls.append(("open_app", params))
        return OperatorResult("ok", self.backend, "opened", {"action": "open_app"}, {"window": {"id": "hwnd:99"}})
```

Replace `test_windows_driver_reports_unsupported_native_actions` with:

```python
def test_windows_driver_open_app_maps_to_native_driver():
    native_driver = FakeNativeDriver()
    driver = WindowsComputerDriver(native_driver=native_driver)

    result = driver.run_action("open_app", app="notepad")

    assert native_driver.calls == [("open_app", {"app": "notepad"})]
    assert result["status"] == "ok"
    assert result["message"] == "opened"
    assert result["observation"]["window"]["id"] == "hwnd:99"
```

Add:

```python
def test_windows_driver_launch_app_maps_to_native_open_app():
    native_driver = FakeNativeDriver()
    driver = WindowsComputerDriver(native_driver=native_driver)

    result = driver.run_action("launch_app", target="brave")

    assert native_driver.calls == [("open_app", {"app": "brave"})]
    assert result["status"] == "ok"
```

- [ ] **Step 3: Run failing tests**

Run:

```powershell
pytest backend/tests/test_computer_use.py::test_computer_use_routes_desktop_open_app_from_target backend/tests/test_computer_use.py::test_computer_use_routes_desktop_launch_app_alias backend/tests/test_computer_use_driver.py::test_windows_driver_open_app_maps_to_native_driver backend/tests/test_computer_use_driver.py::test_windows_driver_launch_app_maps_to_native_open_app -v
```

Expected: FAIL because `open_app` and `launch_app` are not in `NATIVE_DESKTOP_ACTIONS`, `_desktop_params` does not normalize `launch_app`, and `WindowsComputerDriver` does not delegate either action.

- [ ] **Step 4: Implement public routing**

In `backend/agent/tools/computer_use.py`, add both actions:

```python
NATIVE_DESKTOP_ACTIONS = {
    "activate_window",
    "click",
    "double_click",
    "drag",
    "hotkey",
    "keypress",
    "launch_app",
    "list_apps",
    "list_windows",
    "observe",
    "open_app",
    "press_key",
    "right_click",
    "screenshot",
    "scroll",
    "type",
    "type_text",
}
```

Also add them to `NATIVE_MUTATING_DESKTOP_ACTIONS`:

```python
NATIVE_MUTATING_DESKTOP_ACTIONS = {
    "activate_window",
    "click",
    "double_click",
    "drag",
    "keypress",
    "launch_app",
    "open_app",
    "press_key",
    "right_click",
    "scroll",
    "type",
    "type_text",
}
```

Update `_desktop_params`:

```python
    if action in {"open_app", "launch_app", "close_app"}:
        _put(params, "app", app or target or text)
```

Update `_desktop_safety_block` so `launch_app` uses `open_apps`:

```python
    if action == "launch_app":
        required_permission = "open_apps"
```

Place that after `required_permission = desktop_tools.CONTROL_PERMISSIONS.get(action)`.

- [ ] **Step 5: Implement adapter routing**

In `backend/agent/computer_use/windows_driver.py`, add before the unsupported return:

```python
        if normalized in {"open_app", "launch_app"}:
            return self._to_dict(self.native_driver.open_app(**self._open_app_params(clean_params)))
```

Add helper method:

```python
    def _open_app_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if "app" not in params and "target" in params:
            params = {**params, "app": params["target"]}
            params.pop("target", None)
        return params
```

- [ ] **Step 6: Verify tests pass**

Run the same command from Step 3.

Expected: PASS.

- [ ] **Step 7: Commit and push**

```powershell
git add backend/agent/tools/computer_use.py backend/agent/computer_use/windows_driver.py backend/tests/test_computer_use.py backend/tests/test_computer_use_driver.py
git commit -m "feat: route native desktop app launch"
git push origin native-windows-computer-use-impl
```

---

## Task 2: Implement Native App Launch and Polling

**Files:**
- Create: `backend/agent/computer_use/native_windows/app_launch.py`
- Modify: `backend/agent/computer_use/native_windows/driver.py`
- Create: `backend/tests/test_native_app_launch.py`
- Modify: `backend/tests/test_native_driver.py`

- [ ] **Step 1: Write app launch unit tests**

Create `backend/tests/test_native_app_launch.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from agent.computer_use.native_windows import app_launch
from agent.computer_use.operator import ComputerWindow


def make_window(app="notepad.exe", title="Untitled - Notepad", hwnd=1):
    return ComputerWindow(
        id=f"hwnd:{hwnd}",
        hwnd=hwnd,
        app=app,
        pid=123,
        title=title,
        bounds={"x": 0, "y": 0, "width": 800, "height": 600},
    )


def test_resolve_notepad_alias_uses_executable_name():
    resolved = app_launch.resolve_app_target("notepad", exists=lambda _path: False)

    assert resolved.executable == "notepad.exe"
    assert resolved.match_terms == ("notepad", "notepad.exe")


def test_resolve_brave_alias_prefers_existing_candidate():
    chosen = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

    resolved = app_launch.resolve_app_target("brave", exists=lambda path: str(path) == chosen)

    assert resolved.executable == chosen
    assert "brave.exe" in resolved.match_terms


def test_resolve_explicit_exe_path_requires_existing_file(tmp_path):
    exe = tmp_path / "demo.exe"
    exe.write_text("", encoding="utf-8")

    resolved = app_launch.resolve_app_target(str(exe), exists=lambda path: Path(path).exists())

    assert resolved.executable == str(exe)
    assert resolved.match_terms == ("demo.exe", "demo")


def test_resolve_explicit_missing_exe_path_raises():
    with pytest.raises(FileNotFoundError, match="Executable path not found"):
        app_launch.resolve_app_target(r"C:\missing\demo.exe", exists=lambda _path: False)


def test_wait_for_launched_window_returns_first_matching_window(monkeypatch):
    calls = {"count": 0}

    def list_windows():
        calls["count"] += 1
        if calls["count"] == 1:
            return []
        return [make_window(app="brave.exe", title="YouTube - Brave")]

    monkeypatch.setattr(app_launch.time, "sleep", lambda _seconds: None)

    window = app_launch.wait_for_launched_window(
        list_windows=list_windows,
        match_terms=("brave", "brave.exe"),
        timeout_seconds=1,
        poll_interval_seconds=0.01,
    )

    assert window.id == "hwnd:1"
    assert calls["count"] == 2


def test_wait_for_launched_window_times_out(monkeypatch):
    monkeypatch.setattr(app_launch.time, "sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError, match="No targetable app window appeared"):
        app_launch.wait_for_launched_window(
            list_windows=lambda: [],
            match_terms=("brave",),
            timeout_seconds=0,
            poll_interval_seconds=0.01,
        )
```

- [ ] **Step 2: Write native driver launch test**

In `backend/tests/test_native_driver.py`, add a fake launcher and this test:

```python
class FakeLauncher:
    def __init__(self):
        self.calls = []

    def launch_app(self, app, *, list_windows):
        self.calls.append(app)
        return list_windows()[0]
```

Update `FakeWindowing.list_windows()` so it returns Brave when useful by allowing constructor args:

```python
class FakeWindowing:
    def __init__(self, bounds=None, app="notepad.exe", title="Untitled - Notepad"):
        self.activated = []
        self.bounds = bounds or {"x": 0, "y": 0, "width": 100, "height": 80}
        self.app = app
        self.title = title
```

Then use `self.app` and `self.title` in `ComputerWindow`.

Add:

```python
def test_driver_open_app_launches_and_returns_window_observation():
    windowing = FakeWindowing(app="brave.exe", title="YouTube - Brave")
    launcher = FakeLauncher()
    driver = WindowsNativeComputerDriver(
        windowing=windowing,
        accessibility=FakeAccessibility(),
        capture=FakeCapture(),
        input_layer=FakeInput(),
        app_launcher=launcher,
    )

    result = driver.open_app("brave")

    assert result.status == "ok"
    assert launcher.calls == ["brave"]
    assert result.message == "Opened app brave."
    assert result.observation["window"]["app"] == "brave.exe"
```

- [ ] **Step 3: Run failing tests**

```powershell
pytest backend/tests/test_native_app_launch.py backend/tests/test_native_driver.py::test_driver_open_app_launches_and_returns_window_observation -v
```

Expected: FAIL because `app_launch.py`, `WindowsNativeComputerDriver.open_app`, and the `app_launcher` dependency do not exist.

- [ ] **Step 4: Implement app_launch module**

Create `backend/agent/computer_use/native_windows/app_launch.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import time
from typing import Callable, Iterable

from agent.computer_use.operator import ComputerWindow


Exists = Callable[[str], bool]
ListWindows = Callable[[], list[ComputerWindow]]


@dataclass(frozen=True)
class ResolvedAppTarget:
    executable: str
    match_terms: tuple[str, ...]


BRAVE_CANDIDATES = (
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
)


def resolve_app_target(app: str, *, exists: Exists | None = None) -> ResolvedAppTarget:
    exists = exists or (lambda path: Path(path).exists())
    clean = str(app or "").strip()
    if not clean:
        raise ValueError("open_app requires an app name or executable path.")

    lower = clean.casefold()
    if lower in {"notepad", "notepad.exe"}:
        return ResolvedAppTarget("notepad.exe", ("notepad", "notepad.exe"))

    if lower in {"brave", "brave.exe", "brave browser"}:
        candidates = list(BRAVE_CANDIDATES)
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(str(Path(local_app_data) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"))
        for candidate in candidates:
            if exists(candidate):
                return ResolvedAppTarget(candidate, ("brave", "brave.exe"))
        return ResolvedAppTarget("brave.exe", ("brave", "brave.exe"))

    if lower.endswith(".exe") or "\\" in clean or "/" in clean:
        if not exists(clean):
            raise FileNotFoundError(f"Executable path not found: {clean}")
        stem = Path(clean).stem
        return ResolvedAppTarget(clean, (Path(clean).name.casefold(), stem.casefold()))

    raise ValueError(f"Unknown app alias: {clean}")


def launch_app(app: str, *, list_windows: ListWindows, timeout_seconds: float = 10.0) -> ComputerWindow:
    resolved = resolve_app_target(app)
    subprocess.Popen([resolved.executable], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return wait_for_launched_window(
        list_windows=list_windows,
        match_terms=resolved.match_terms,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=0.25,
    )


def wait_for_launched_window(
    *,
    list_windows: ListWindows,
    match_terms: Iterable[str],
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> ComputerWindow:
    terms = tuple(str(term).casefold() for term in match_terms if str(term).strip())
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        for window in list_windows():
            text = f"{window.app} {window.title}".casefold()
            if any(term in text for term in terms):
                return window
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_interval_seconds)
    joined = ", ".join(terms)
    raise TimeoutError(f"No targetable app window appeared before timeout: {joined}")
```

- [ ] **Step 5: Add native driver launch dependency**

In `backend/agent/computer_use/native_windows/driver.py`, import:

```python
from agent.computer_use.native_windows import app_launch as default_app_launch
```

Update `__init__`:

```python
        app_launcher=default_app_launch,
```

and assign:

```python
        self.app_launcher = app_launcher
```

Add method:

```python
    def open_app(self, app: str) -> OperatorResult:
        window = self.app_launcher.launch_app(app, list_windows=self.windowing.list_windows)
        try:
            window = self.windowing.activate_window(window.id)
        except Exception:
            window = self.windowing.get_window(window.id)
        result = self.get_window_state(window.id)
        return OperatorResult("ok", self.backend, f"Opened app {app}.", observation=result.observation)
```

- [ ] **Step 6: Verify tests pass**

```powershell
pytest backend/tests/test_native_app_launch.py backend/tests/test_native_driver.py::test_driver_open_app_launches_and_returns_window_observation -v
```

Expected: PASS.

- [ ] **Step 7: Commit and push**

```powershell
git add backend/agent/computer_use/native_windows/app_launch.py backend/agent/computer_use/native_windows/driver.py backend/tests/test_native_app_launch.py backend/tests/test_native_driver.py
git commit -m "feat: add native Windows app launch"
git push origin native-windows-computer-use-impl
```

---

## Task 3: Add Activation Recovery for Mutating Actions

**Files:**
- Modify: `backend/agent/computer_use/native_windows/driver.py`
- Modify: `backend/tests/test_native_driver.py`

- [ ] **Step 1: Write recovery tests**

In `backend/tests/test_native_driver.py`, add:

```python
class RecoveringWindowing(FakeWindowing):
    def __init__(self):
        super().__init__(app="brave.exe", title="YouTube - Brave")
        self.fail_once = True
        self.get_calls = []

    def activate_window(self, window_id):
        self.activated.append(window_id)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError(f"Failed to activate window: {window_id}")
        return self.list_windows()[0]

    def get_window(self, window_id):
        self.get_calls.append(window_id)
        return self.list_windows()[0]


def test_driver_click_recovers_after_first_activation_failure():
    windowing = RecoveringWindowing()
    input_layer = FakeInput()
    driver = WindowsNativeComputerDriver(
        windowing=windowing,
        accessibility=FakeAccessibility(),
        capture=FakeCapture(),
        input_layer=input_layer,
    )

    result = driver.click("hwnd:1", x=10, y=20)

    assert result.status == "ok"
    assert windowing.activated == ["hwnd:1", "hwnd:1"]
    assert windowing.get_calls == ["hwnd:1"]
    assert input_layer.calls[0][0] == "click"
```

Add:

```python
class AmbiguousRecoveryWindowing(RecoveringWindowing):
    def list_windows(self):
        from agent.computer_use.operator import ComputerWindow

        return [
            ComputerWindow("hwnd:1", 1, "brave.exe", 2, "YouTube - Brave", self.bounds),
            ComputerWindow("hwnd:2", 2, "brave.exe", 2, "New Tab - Brave", self.bounds),
        ]

    def get_window(self, window_id):
        raise RuntimeError(f"Window is not targetable: {window_id}")


def test_driver_click_reports_ambiguous_activation_recovery():
    driver = WindowsNativeComputerDriver(
        windowing=AmbiguousRecoveryWindowing(),
        accessibility=FakeAccessibility(),
        capture=FakeCapture(),
        input_layer=FakeInput(),
    )

    try:
        driver.click("hwnd:1", x=10, y=20)
    except RuntimeError as exc:
        assert "Activation recovery is ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous recovery should raise")
```

- [ ] **Step 2: Run failing tests**

```powershell
pytest backend/tests/test_native_driver.py::test_driver_click_recovers_after_first_activation_failure backend/tests/test_native_driver.py::test_driver_click_reports_ambiguous_activation_recovery -v
```

Expected: FAIL because `_activate_or_resolve` raises immediately.

- [ ] **Step 3: Implement activation recovery**

In `backend/agent/computer_use/native_windows/driver.py`, replace `_activate_or_resolve` with:

```python
    def _activate_or_resolve(self, window_id: str | None) -> ComputerWindow:
        if not window_id:
            return self.windowing.active_window()
        try:
            return self.windowing.activate_window(window_id)
        except Exception as first_error:
            try:
                refreshed = self.windowing.get_window(window_id)
            except Exception:
                refreshed = self._recover_single_window_for_failed_target(window_id, first_error)
            try:
                return self.windowing.activate_window(refreshed.id)
            except Exception as second_error:
                raise RuntimeError(
                    f"Failed to activate window after recovery: {refreshed.id}; "
                    f"first_error={first_error}; second_error={second_error}"
                ) from second_error
```

Add helper:

```python
    def _recover_single_window_for_failed_target(
        self,
        window_id: str,
        first_error: Exception,
    ) -> ComputerWindow:
        candidates = self.windowing.list_windows()
        if len(candidates) == 1:
            return candidates[0]
        raise RuntimeError(
            f"Activation recovery is ambiguous for {window_id}: "
            f"{len(candidates)} targetable windows found; first_error={first_error}"
        ) from first_error
```

- [ ] **Step 4: Verify recovery tests pass**

```powershell
pytest backend/tests/test_native_driver.py::test_driver_click_recovers_after_first_activation_failure backend/tests/test_native_driver.py::test_driver_click_reports_ambiguous_activation_recovery -v
```

Expected: PASS.

- [ ] **Step 5: Run native driver regression tests**

```powershell
pytest backend/tests/test_native_driver.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit and push**

```powershell
git add backend/agent/computer_use/native_windows/driver.py backend/tests/test_native_driver.py
git commit -m "fix: recover native window activation"
git push origin native-windows-computer-use-impl
```

---

## Task 4: Fix Input Guard Hook Pointer Signatures

**Files:**
- Modify: `backend/agent/computer_use/input_guard.py`
- Create: `backend/tests/test_input_guard.py`

- [ ] **Step 1: Write signature tests**

Create `backend/tests/test_input_guard.py`:

```python
from __future__ import annotations

import ctypes

from agent.computer_use import input_guard


def test_low_level_hook_proc_uses_pointer_sized_lresult():
    proc_type = input_guard.WindowsInputGuard._low_level_proc_type()

    assert proc_type._restype_ is input_guard.LRESULT
    assert proc_type._argtypes_[0] is ctypes.c_int
    assert proc_type._argtypes_[1] is input_guard.WPARAM
    assert proc_type._argtypes_[2] is input_guard.LPARAM


def test_configure_hook_api_sets_call_next_hook_ex_signature():
    class FakeFunction:
        pass

    class FakeUser32:
        CallNextHookEx = FakeFunction()
        SetWindowsHookExW = FakeFunction()
        UnhookWindowsHookEx = FakeFunction()

    fake = FakeUser32()
    input_guard.WindowsInputGuard._configure_hook_api(fake)

    assert fake.CallNextHookEx.restype is input_guard.LRESULT
    assert fake.CallNextHookEx.argtypes == [input_guard.HHOOK, ctypes.c_int, input_guard.WPARAM, input_guard.LPARAM]
```

- [ ] **Step 2: Run failing tests**

```powershell
pytest backend/tests/test_input_guard.py -v
```

Expected: FAIL because `_low_level_proc_type`, `_configure_hook_api`, `LRESULT`, `WPARAM`, `LPARAM`, and `HHOOK` are not exposed as module-level names.

- [ ] **Step 3: Implement pointer-safe types**

In `backend/agent/computer_use/input_guard.py`, add near imports:

```python
LRESULT = ctypes.c_ssize_t
WPARAM = wintypes.WPARAM
LPARAM = wintypes.LPARAM
HHOOK = wintypes.HANDLE
```

Inside `WindowsInputGuard`, add:

```python
    @staticmethod
    def _low_level_proc_type():
        return ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)

    @staticmethod
    def _configure_hook_api(user32) -> None:
        user32.CallNextHookEx.argtypes = [HHOOK, ctypes.c_int, WPARAM, LPARAM]
        user32.CallNextHookEx.restype = LRESULT
        user32.SetWindowsHookExW.restype = HHOOK
        user32.UnhookWindowsHookEx.argtypes = [HHOOK]
```

In `_message_loop`, replace:

```python
            low_level_proc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
```

with:

```python
            self._configure_hook_api(user32)
            low_level_proc = self._low_level_proc_type()
```

In `_keyboard_callback` and `_mouse_callback`, cast `w_param` and `l_param` before passing to `CallNextHookEx`:

```python
            return user32.CallNextHookEx(self._keyboard_hook, int(n_code), WPARAM(w_param), LPARAM(l_param))
```

Use the same shape for mouse:

```python
            return user32.CallNextHookEx(self._mouse_hook, int(n_code), WPARAM(w_param), LPARAM(l_param))
```

- [ ] **Step 4: Verify input guard tests pass**

```powershell
pytest backend/tests/test_input_guard.py -v
```

Expected: PASS.

- [ ] **Step 5: Run session tests**

```powershell
pytest backend/tests/test_computer_use_session.py backend/tests/test_api.py::test_computer_use_enable_starts_activity_overlay backend/tests/test_api.py::test_computer_use_disable_stops_activity_overlay -v
```

Expected: PASS.

- [ ] **Step 6: Commit and push**

```powershell
git add backend/agent/computer_use/input_guard.py backend/tests/test_input_guard.py
git commit -m "fix: use pointer-safe input guard hooks"
git push origin native-windows-computer-use-impl
```

---

## Task 5: Smooth Blue Overlay Glow and Lower Status Pill

**Files:**
- Modify: `backend/agent/computer_use/native_windows/overlay.py`
- Modify: `backend/tests/test_computer_use_session.py`
- Modify: `backend/tests/test_native_overlay.py`

- [ ] **Step 1: Update overlay expectations**

In `backend/tests/test_computer_use_session.py`, update `test_native_overlay_script_uses_transparent_glow_and_status_pill`:

```python
def test_native_overlay_script_uses_transparent_glow_and_status_pill():
    from agent.computer_use.native_windows import overlay

    script = overlay._overlay_script()

    assert "Vellum is using your computer" in overlay.OVERLAY_MESSAGE
    assert "TRANSPARENT_COLOR" in script
    assert "root.attributes(\"-transparentcolor\", TRANSPARENT_COLOR)" in script
    assert "ImageDraw" in script
    assert "ImageTk.PhotoImage" in script
    assert "EDGE_GLOW_DESIGN" in script
    assert "pill_y1 = 32" in script
    assert "for inset, color, line_width in" not in script
    assert "create_rectangle(" not in script
```

In `backend/tests/test_native_overlay.py`, add:

```python
def test_native_overlay_status_reports_smooth_single_glow_design():
    from agent.computer_use.native_windows.overlay import NativeWindowsOverlayController

    status = NativeWindowsOverlayController().status()

    assert status["design"] == "smooth_single_edge_glow_status_pill"
    assert status["edge_glow"] is True
    assert status["status_pill"] is True
    assert status["pill_offset_y"] == 32
```

- [ ] **Step 2: Run failing overlay tests**

```powershell
pytest backend/tests/test_computer_use_session.py::test_native_overlay_script_uses_transparent_glow_and_status_pill backend/tests/test_native_overlay.py::test_native_overlay_status_reports_smooth_single_glow_design -v
```

Expected: FAIL because current overlay uses multiple rectangles and old design metadata.

- [ ] **Step 3: Implement smooth overlay constants**

In `backend/agent/computer_use/native_windows/overlay.py`, update constants:

```python
OVERLAY_BLUE = "#168cff"
OVERLAY_BLUE_DARK = "#0757bd"
OVERLAY_BLUE_LIGHT = "#8fd1ff"
OVERLAY_MESSAGE = "Vellum is using your computer - Esc to cancel"
OVERLAY_DESIGN = "smooth_single_edge_glow_status_pill"
PILL_OFFSET_Y = 32
```

- [ ] **Step 4: Replace edge rendering in `_overlay_script`**

Replace the `edge_items` rectangle loop with this Pillow-backed image block:

```python
EDGE_GLOW_DESIGN = "smooth-single-glow"
try:
    from PIL import Image, ImageDraw, ImageFilter, ImageTk

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    for inset, alpha, stroke in ((14, 150, 4), (20, 95, 10), (30, 45, 18)):
        draw.rounded_rectangle(
            [inset, inset, width - inset - 1, height - inset - 1],
            radius=22,
            outline=(22, 140, 255, alpha),
            width=stroke,
        )
    glow = glow.filter(ImageFilter.GaussianBlur(5))
    crisp = ImageDraw.Draw(glow)
    crisp.rounded_rectangle(
        [18, 18, width - 19, height - 19],
        radius=20,
        outline=(143, 209, 255, 190),
        width=2,
    )
    glow_image = ImageTk.PhotoImage(glow)
    canvas.create_image(0, 0, image=glow_image, anchor="nw")
    canvas._glow_image = glow_image
except Exception:
    canvas.create_line(18, 18, width - 18, 18, fill=BLUE_LIGHT, width=2)
    canvas.create_line(width - 18, 18, width - 18, height - 18, fill=BLUE, width=2)
    canvas.create_line(width - 18, height - 18, 18, height - 18, fill=BLUE, width=2)
    canvas.create_line(18, height - 18, 18, 18, fill=BLUE_LIGHT, width=2)
```

Set pill position:

```python
pill_y1 = 32
```

Remove `edge_items` and remove the edge color animation from `pulse`. Keep a subtle pill pulse:

```python
def pulse(step=0):
    canvas.itemconfigure(pill, fill=BLUE if step % 2 == 0 else BLUE_DARK, outline=BLUE_LIGHT)
    root.after(650, pulse, step + 1)
```

- [ ] **Step 5: Update status metadata**

In `NativeWindowsOverlayController.status`, add:

```python
            "pill_offset_y": PILL_OFFSET_Y,
            "edge_glow_style": "smooth-single",
```

- [ ] **Step 6: Verify overlay tests pass**

```powershell
pytest backend/tests/test_computer_use_session.py::test_native_overlay_script_uses_transparent_glow_and_status_pill backend/tests/test_native_overlay.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit and push**

```powershell
git add backend/agent/computer_use/native_windows/overlay.py backend/tests/test_computer_use_session.py backend/tests/test_native_overlay.py
git commit -m "fix: smooth native computer use overlay"
git push origin native-windows-computer-use-impl
```

---

## Task 6: Full Verification and Manual Smoke Tests

**Files:**
- No source files expected unless tests expose a defect.
- Generated files under `data/computer-use/` must not be committed.

- [ ] **Step 1: Run focused automated suite**

```powershell
pytest backend/tests/test_computer_use_operator.py backend/tests/test_native_windowing.py backend/tests/test_native_accessibility.py backend/tests/test_native_capture.py backend/tests/test_native_input.py backend/tests/test_native_app_launch.py backend/tests/test_native_driver.py backend/tests/test_computer_use_driver.py backend/tests/test_computer_use_router.py backend/tests/test_computer_use_session.py backend/tests/test_native_overlay.py backend/tests/test_input_guard.py backend/tests/test_computer_use.py backend/tests/test_agent_prompt.py backend/tests/test_config.py backend/tests/test_api.py -v
```

Expected: PASS.

- [ ] **Step 2: Run manual Notepad smoke**

From `backend/`, run a Python script that:

```python
import os
import time

os.environ["COMPUTER_USE_ALLOW_DESKTOP"] = "true"
os.environ.setdefault("OPENROUTER_API_KEY", "manual-smoke-key")
os.environ.setdefault("OBSIDIAN_VAULT_PATH", r"C:\Users\User\OneDrive\Desktop\Vellum")
os.environ.setdefault("FILESYSTEM_MCP_PATH", r"C:\Users\User\OneDrive\Desktop\Vellum")

from agent.computer_use.session import computer_use_session
from agent.tools import computer_use as computer_use_tools

tool = computer_use_tools.computer_use
computer_use_session.start(source="manual-smoke", task="Notepad native computer use smoke test")
try:
    tool.invoke({"mode": "desktop", "action": "grant_permission", "permission": "open_apps", "confirm": True})
    tool.invoke({"mode": "desktop", "action": "grant_permission", "permission": "desktop_control", "confirm": True})
    result = tool.invoke({"mode": "desktop", "action": "open_app", "app": "notepad"})
    print(result)
    time.sleep(1)
    windows = computer_use_tools.desktop_driver.run_action("list_windows")
    notepad = next(window for window in windows["data"]["windows"] if "notepad" in f"{window['app']} {window['title']}".lower())
    target = notepad["id"]
    print(tool.invoke({"mode": "desktop", "action": "type", "target": target, "text": "Vellum native computer use test"}))
    time.sleep(1)
    print(tool.invoke({"mode": "desktop", "action": "keypress", "target": target, "key": "alt+f4"}))
    time.sleep(1)
    refreshed = computer_use_tools.desktop_driver.run_action("list_windows")
    save_prompt = next((window for window in refreshed["data"]["windows"] if "notepad" in f"{window['app']} {window['title']}".lower()), None)
    if save_prompt:
        print(tool.invoke({"mode": "desktop", "action": "keypress", "target": save_prompt["id"], "key": "tab"}))
        print(tool.invoke({"mode": "desktop", "action": "keypress", "target": save_prompt["id"], "key": "enter"}))
finally:
    computer_use_session.stop(source="manual-smoke", reason="Notepad smoke complete")
```

Expected visible result:

- Blue overlay appears.
- Notepad opens.
- Text appears in Notepad.
- Notepad closes.
- No input guard callback warning appears.

- [ ] **Step 3: Run manual Brave smoke**

From `backend/`, run a Python script that:

```python
import os
import time

os.environ["COMPUTER_USE_ALLOW_DESKTOP"] = "true"
os.environ.setdefault("OPENROUTER_API_KEY", "manual-smoke-key")
os.environ.setdefault("OBSIDIAN_VAULT_PATH", r"C:\Users\User\OneDrive\Desktop\Vellum")
os.environ.setdefault("FILESYSTEM_MCP_PATH", r"C:\Users\User\OneDrive\Desktop\Vellum")

from agent.computer_use.session import computer_use_session
from agent.tools import computer_use as computer_use_tools

tool = computer_use_tools.computer_use
computer_use_session.start(source="manual-smoke", task="Brave native computer use smoke test")
try:
    tool.invoke({"mode": "desktop", "action": "grant_permission", "permission": "open_apps", "confirm": True})
    tool.invoke({"mode": "desktop", "action": "grant_permission", "permission": "desktop_control", "confirm": True})
    print(tool.invoke({"mode": "desktop", "action": "open_app", "app": "brave"}))
    time.sleep(2)
    windows = computer_use_tools.desktop_driver.run_action("list_windows")
    brave = next(window for window in windows["data"]["windows"] if "brave" in f"{window['app']} {window['title']}".lower())
    target = brave["id"]
    print(tool.invoke({"mode": "desktop", "action": "keypress", "target": target, "key": "ctrl+l"}))
    print(tool.invoke({"mode": "desktop", "action": "type", "target": target, "text": "https://www.youtube.com"}))
    print(tool.invoke({"mode": "desktop", "action": "keypress", "target": target, "key": "enter"}))
    time.sleep(5)
    print(tool.invoke({"mode": "desktop", "action": "keypress", "target": target, "key": "alt+f4"}))
finally:
    computer_use_session.stop(source="manual-smoke", reason="Brave smoke complete")
```

Expected visible result:

- Blue overlay appears.
- Brave opens.
- Address bar receives `https://www.youtube.com`.
- YouTube loads.
- Brave closes.
- No input guard callback warning appears.

- [ ] **Step 4: Check git status and avoid generated artifacts**

```powershell
git status --short --branch
```

Expected:

- Source/test changes are committed.
- `data/computer-use/*` generated smoke-test files may be dirty or untracked.
- Do not commit generated smoke-test data unless the user explicitly asks.

- [ ] **Step 5: Final push check**

```powershell
git log --oneline -6
git status --short --branch
```

Expected:

- Branch is pushed to `origin/native-windows-computer-use-impl`.
- Only ignored/generated computer-use artifacts remain dirty.
