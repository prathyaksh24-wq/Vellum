# Native Windows Computer Use Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Vellum's `pyautogui` desktop computer-use path with a native Windows driver that can list windows, observe a target window with screenshot/accessibility data, and perform guarded SendInput actions.

**Architecture:** Add focused native modules under `backend/agent/computer_use/native_windows/` for Win32 windowing, UI Automation, capture, input, overlay, and driver assembly. Keep the existing public `computer_use` tool, runtime mode, event feed, permissions, input guard, and Playwright browser specialist, but route desktop mode to the native driver. Add a disabled Codex fallback adapter behind the same operator interface.

**Tech Stack:** Python 3.11+, `ctypes` Win32 APIs, `comtypes` UI Automation, Pillow native bitmap conversion, FastAPI/LangChain existing tool surface, pytest.

---

## Branch And Commit Rules

- Work on branch `native-windows-computer-use`.
- Commit after each task passes its task-level tests.
- Push `origin native-windows-computer-use` after each task commit.
- Do not commit or push directly to `main`.
- Keep `pyautogui` out of the final production desktop path and remove it from dependencies before the final verification task.

## File Map

- Create `backend/agent/computer_use/operator.py`: common operator protocol, window/action dataclasses, and disabled Codex fallback adapter contract.
- Create `backend/agent/computer_use/native_windows/__init__.py`: package export surface.
- Create `backend/agent/computer_use/native_windows/windowing.py`: Win32 window enumeration, metadata, activation, and browser URL confidence helper hooks.
- Create `backend/agent/computer_use/native_windows/accessibility.py`: UI Automation tree extraction and normalized element indexes.
- Create `backend/agent/computer_use/native_windows/capture.py`: native window screenshot capture saved to disk.
- Create `backend/agent/computer_use/native_windows/input.py`: SendInput key/mouse construction and action helpers.
- Create `backend/agent/computer_use/native_windows/overlay.py`: transparent full-screen click-through overlay with blue edge glow, top status pill, and Esc-to-exit callback.
- Create `backend/agent/computer_use/native_windows/driver.py`: `WindowsNativeComputerDriver` composing the native modules.
- Modify `backend/agent/computer_use/windows_driver.py`: delegate to `WindowsNativeComputerDriver` instead of `agent.tools.desktop`.
- Modify `backend/agent/computer_use/router.py`: accept native action names and backend provenance.
- Modify `backend/agent/tools/computer_use.py`: route expanded desktop actions to the structured driver.
- Modify `backend/agent/computer_use/overlay.py`: replace `desktop_tools` overlay calls with native overlay controller.
- Modify `backend/agent/config.py`: add native driver settings if needed and remove `pyautogui` assumptions.
- Modify `backend/requirements.txt`: add `comtypes` and `psutil` on Windows; remove `pyautogui`.
- Modify `backend/pyproject.toml`: add `comtypes` and remove `pyautogui`.
- Modify tests in `backend/tests/`: add focused native tests and update old `pyautogui` expectations.

---

### Task 1: Operator Contract And Codex Fallback Stub

**Files:**
- Create: `backend/agent/computer_use/operator.py`
- Create: `backend/tests/test_computer_use_operator.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_computer_use_operator.py`:

```python
from agent.computer_use.operator import (
    CodexComputerUseAdapter,
    ComputerWindow,
    OperatorResult,
)


def test_computer_window_serializes_to_public_dict():
    window = ComputerWindow(
        id="hwnd:100",
        hwnd=100,
        app="notepad.exe",
        pid=42,
        title="Untitled - Notepad",
        bounds={"x": 1, "y": 2, "width": 800, "height": 600},
    )

    assert window.to_dict()["id"] == "hwnd:100"
    assert window.to_dict()["bounds"]["width"] == 800


def test_operator_result_carries_backend_and_observation():
    result = OperatorResult(
        status="ok",
        backend="windows_native",
        message="Observed.",
        data={"window_id": "hwnd:100"},
        observation={"accessibility_tree": "button 1"},
    )

    assert result.to_dict()["backend"] == "windows_native"
    assert result.to_dict()["observation"]["accessibility_tree"] == "button 1"


def test_codex_adapter_is_disabled_by_default():
    adapter = CodexComputerUseAdapter()

    assert adapter.health_check()["ok"] is False
    assert adapter.list_windows().status == "unavailable"
    assert "unavailable" in adapter.list_windows().message.casefold()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_computer_use_operator.py -v
```

Expected: import error because `agent.computer_use.operator` does not exist.

- [ ] **Step 3: Implement the operator contract**

Create `backend/agent/computer_use/operator.py`:

```python
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
    def get_window_state(self, window_id: str | None = None, *, include_screenshot: bool = True, include_text: bool = True) -> OperatorResult: ...
    def activate_window(self, window_id: str) -> OperatorResult: ...
    def click(self, window_id: str | None = None, *, element_index: int | None = None, x: int | None = None, y: int | None = None, button: str = "left", click_count: int = 1) -> OperatorResult: ...
    def type_text(self, text: str, window_id: str | None = None) -> OperatorResult: ...
    def press_key(self, key: str, window_id: str | None = None) -> OperatorResult: ...
    def scroll(self, window_id: str | None = None, *, x: int = 0, y: int = 0, scroll_x: int = 0, scroll_y: int = 0) -> OperatorResult: ...
    def drag(self, window_id: str | None = None, *, from_x: int, from_y: int, to_x: int, to_y: int) -> OperatorResult: ...


class CodexComputerUseAdapter:
    backend = "codex_fallback"

    def health_check(self) -> dict[str, Any]:
        return {"ok": False, "backend": self.backend, "message": "Codex Computer Use fallback is unavailable."}

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

    def get_window_state(self, window_id: str | None = None, *, include_screenshot: bool = True, include_text: bool = True) -> OperatorResult:
        return self._unavailable("get_window_state")

    def activate_window(self, window_id: str) -> OperatorResult:
        return self._unavailable("activate_window")

    def click(self, window_id: str | None = None, *, element_index: int | None = None, x: int | None = None, y: int | None = None, button: str = "left", click_count: int = 1) -> OperatorResult:
        return self._unavailable("click")

    def type_text(self, text: str, window_id: str | None = None) -> OperatorResult:
        return self._unavailable("type_text")

    def press_key(self, key: str, window_id: str | None = None) -> OperatorResult:
        return self._unavailable("press_key")

    def scroll(self, window_id: str | None = None, *, x: int = 0, y: int = 0, scroll_x: int = 0, scroll_y: int = 0) -> OperatorResult:
        return self._unavailable("scroll")

    def drag(self, window_id: str | None = None, *, from_x: int, from_y: int, to_x: int, to_y: int) -> OperatorResult:
        return self._unavailable("drag")
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_computer_use_operator.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit and push**

Run:

```powershell
git add backend/agent/computer_use/operator.py backend/tests/test_computer_use_operator.py
git commit -m "feat: add computer use operator contract"
git push origin native-windows-computer-use
```

---

### Task 2: Native Window Discovery

**Files:**
- Create: `backend/agent/computer_use/native_windows/__init__.py`
- Create: `backend/agent/computer_use/native_windows/windowing.py`
- Create: `backend/tests/test_native_windowing.py`

- [ ] **Step 1: Write failing tests for handle parsing and normalization**

Create `backend/tests/test_native_windowing.py`:

```python
from agent.computer_use.operator import ComputerWindow
from agent.computer_use.native_windows import windowing


def test_window_id_round_trip():
    assert windowing.window_id(1234) == "hwnd:1234"
    assert windowing.parse_window_id("hwnd:1234") == 1234
    assert windowing.parse_window_id("1234") == 1234


def test_invalid_window_id_is_rejected():
    try:
        windowing.parse_window_id("window:abc")
    except ValueError as exc:
        assert "Invalid window id" in str(exc)
    else:
        raise AssertionError("parse_window_id should reject invalid ids")


def test_normalize_window_skips_empty_titles():
    result = windowing.normalize_window(hwnd=10, title="", pid=2, app="notepad.exe", bounds=(1, 2, 3, 4))

    assert result is None


def test_normalize_window_returns_computer_window():
    result = windowing.normalize_window(
        hwnd=10,
        title="Untitled - Notepad",
        pid=2,
        app="notepad.exe",
        bounds=(1, 2, 801, 602),
    )

    assert isinstance(result, ComputerWindow)
    assert result.id == "hwnd:10"
    assert result.bounds == {"x": 1, "y": 2, "width": 800, "height": 600}
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_native_windowing.py -v
```

Expected: import error for `agent.computer_use.native_windows`.

- [ ] **Step 3: Implement testable window normalization**

Create `backend/agent/computer_use/native_windows/__init__.py`:

```python
"""Native Windows computer-use backend."""
```

Create `backend/agent/computer_use/native_windows/windowing.py` with the testable helpers plus real Win32 functions:

```python
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Callable

from agent.computer_use.operator import ComputerWindow


def window_id(hwnd: int) -> str:
    return f"hwnd:{int(hwnd)}"


def parse_window_id(value: str | int) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.startswith("hwnd:"):
        text = text.removeprefix("hwnd:")
    if not text.isdigit():
        raise ValueError(f"Invalid window id: {value}")
    return int(text)


def normalize_window(*, hwnd: int, title: str, pid: int, app: str, bounds: tuple[int, int, int, int]) -> ComputerWindow | None:
    clean_title = " ".join(str(title or "").split())
    if not clean_title:
        return None
    left, top, right, bottom = bounds
    width = max(0, int(right) - int(left))
    height = max(0, int(bottom) - int(top))
    if width <= 0 or height <= 0:
        return None
    return ComputerWindow(
        id=window_id(hwnd),
        hwnd=int(hwnd),
        app=app or "unknown",
        pid=int(pid),
        title=clean_title,
        bounds={"x": int(left), "y": int(top), "width": width, "height": height},
    )


def list_windows() -> list[ComputerWindow]:
    if not _is_windows():
        return []
    user32 = ctypes.windll.user32
    windows: list[ComputerWindow] = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @enum_proc
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_text(hwnd)
        pid = _window_pid(hwnd)
        app = _process_name(pid)
        bounds = _window_bounds(hwnd)
        normalized = normalize_window(hwnd=int(hwnd), title=title, pid=pid, app=app, bounds=bounds)
        if normalized is not None:
            windows.append(normalized)
        return True

    user32.EnumWindows(callback, 0)
    return windows


def get_window(value: str | int) -> ComputerWindow:
    hwnd = parse_window_id(value)
    if not _is_windows():
        raise RuntimeError("Native Windows computer use requires Windows.")
    normalized = normalize_window(
        hwnd=hwnd,
        title=_window_text(hwnd),
        pid=_window_pid(hwnd),
        app=_process_name(_window_pid(hwnd)),
        bounds=_window_bounds(hwnd),
    )
    if normalized is None:
        raise RuntimeError(f"Window is not targetable: {value}")
    return normalized


def active_window() -> ComputerWindow:
    hwnd = int(ctypes.windll.user32.GetForegroundWindow())
    return get_window(hwnd)


def activate_window(value: str | int) -> ComputerWindow:
    hwnd = parse_window_id(value)
    if not _is_windows():
        raise RuntimeError("Native Windows computer use requires Windows.")
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    return get_window(hwnd)


def _is_windows() -> bool:
    return hasattr(ctypes, "windll")


def _window_text(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _window_bounds(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _process_name(pid: int) -> str:
    try:
        import psutil
    except ImportError:
        return f"pid:{pid}"
    try:
        process = psutil.Process(pid)
        return Path(process.exe()).name or process.name()
    except Exception:
        return f"pid:{pid}"
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_native_windowing.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit and push**

Run:

```powershell
git add backend/agent/computer_use/native_windows/__init__.py backend/agent/computer_use/native_windows/windowing.py backend/tests/test_native_windowing.py
git commit -m "feat: add native window discovery primitives"
git push origin native-windows-computer-use
```

---

### Task 3: Accessibility Tree Normalization

**Files:**
- Create: `backend/agent/computer_use/native_windows/accessibility.py`
- Create: `backend/tests/test_native_accessibility.py`

- [ ] **Step 1: Write failing tests with fake UIA nodes**

Create `backend/tests/test_native_accessibility.py`:

```python
from agent.computer_use.native_windows import accessibility


class FakeNode:
    def __init__(self, name, control_type="Button", bounds=(1, 2, 11, 12), children=None):
        self.name = name
        self.control_type = control_type
        self.bounds = bounds
        self.children = children or []


def test_normalize_tree_assigns_stable_indexes():
    root = FakeNode("Root", "Window", children=[FakeNode("OK"), FakeNode("Cancel")])

    state = accessibility.normalize_fake_tree(root)

    assert state["tree"].splitlines()[0].startswith("[0] Window")
    assert "[1] Button name='OK'" in state["tree"]
    assert state["elements"][2]["name"] == "Cancel"
    assert state["elements"][1]["bounds"] == {"x": 1, "y": 2, "width": 10, "height": 10}


def test_element_center_uses_index_bounds():
    state = {"elements": [{"index": 0, "bounds": {"x": 10, "y": 20, "width": 30, "height": 40}}]}

    assert accessibility.element_center(state, 0) == (25, 40)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_native_accessibility.py -v
```

Expected: import error for `accessibility`.

- [ ] **Step 3: Implement normalization and lazy UIA entrypoint**

Create `backend/agent/computer_use/native_windows/accessibility.py`:

```python
from __future__ import annotations

from typing import Any


MAX_DEPTH = 8
MAX_NODES = 250


def normalize_fake_tree(root: Any) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    lines: list[str] = []

    def walk(node: Any, depth: int) -> None:
        if depth > MAX_DEPTH or len(elements) >= MAX_NODES:
            return
        index = len(elements)
        bounds = _bounds_dict(getattr(node, "bounds", (0, 0, 0, 0)))
        item = {
            "index": index,
            "role": str(getattr(node, "control_type", "Unknown") or "Unknown"),
            "name": str(getattr(node, "name", "") or ""),
            "bounds": bounds,
        }
        elements.append(item)
        indent = "  " * depth
        name = f" name='{item['name']}'" if item["name"] else ""
        lines.append(f"{indent}[{index}] {item['role']}{name} bounds={bounds['x']},{bounds['y']},{bounds['width']}x{bounds['height']}")
        for child in list(getattr(node, "children", []) or []):
            walk(child, depth + 1)

    walk(root, 0)
    return {"tree": "\n".join(lines), "elements": elements}


def get_accessibility_state(hwnd: int, *, include_text: bool = True) -> dict[str, Any]:
    if not include_text:
        return {"tree": "", "elements": []}
    try:
        import comtypes.client
    except ImportError as exc:
        return {"tree": "", "elements": [], "error": "Windows accessibility requires comtypes."}

    try:
        uia = comtypes.client.CreateObject("UIAutomationClient.CUIAutomation")
        element = uia.ElementFromHandle(hwnd)
    except Exception as exc:
        return {"tree": "", "elements": [], "error": f"Windows accessibility failed: {exc}"}
    return _normalize_uia_element(element)


def element_center(state: dict[str, Any], element_index: int) -> tuple[int, int]:
    for element in state.get("elements", []):
        if int(element.get("index", -1)) == int(element_index):
            bounds = element["bounds"]
            return int(bounds["x"] + bounds["width"] / 2), int(bounds["y"] + bounds["height"] / 2)
    raise ValueError(f"Element index not found: {element_index}")


def _normalize_uia_element(root: Any) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    lines: list[str] = []

    def walk(node: Any, depth: int) -> None:
        if depth > MAX_DEPTH or len(elements) >= MAX_NODES:
            return
        index = len(elements)
        bounds = _uia_bounds(node)
        role = _control_type_name(getattr(node, "CurrentControlType", 0))
        name = str(getattr(node, "CurrentName", "") or "")
        item = {"index": index, "role": role, "name": name, "bounds": bounds}
        elements.append(item)
        indent = "  " * depth
        label = f" name='{name}'" if name else ""
        lines.append(f"{indent}[{index}] {role}{label} bounds={bounds['x']},{bounds['y']},{bounds['width']}x{bounds['height']}")
        try:
            walker = node.GetCurrentPropertyValue
        except Exception:
            return

    walk(root, 0)
    return {"tree": "\n".join(lines), "elements": elements}


def _bounds_dict(bounds: tuple[int, int, int, int]) -> dict[str, int]:
    left, top, right, bottom = [int(value) for value in bounds]
    return {"x": left, "y": top, "width": max(0, right - left), "height": max(0, bottom - top)}


def _uia_bounds(node: Any) -> dict[str, int]:
    rect = getattr(node, "CurrentBoundingRectangle", None)
    if rect is None:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    return {
        "x": int(getattr(rect, "left", 0)),
        "y": int(getattr(rect, "top", 0)),
        "width": max(0, int(getattr(rect, "right", 0)) - int(getattr(rect, "left", 0))),
        "height": max(0, int(getattr(rect, "bottom", 0)) - int(getattr(rect, "top", 0))),
    }


def _control_type_name(control_type: int) -> str:
    names = {
        50032: "Window",
        50000: "Button",
        50004: "Edit",
        50005: "Hyperlink",
        50020: "Text",
        50033: "Pane",
        50036: "TitleBar",
    }
    return names.get(int(control_type or 0), f"ControlType:{control_type}")
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_native_accessibility.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit and push**

Run:

```powershell
git add backend/agent/computer_use/native_windows/accessibility.py backend/tests/test_native_accessibility.py
git commit -m "feat: normalize native accessibility trees"
git push origin native-windows-computer-use
```

---

### Task 4: Native Screenshot Capture

**Files:**
- Create: `backend/agent/computer_use/native_windows/capture.py`
- Create: `backend/tests/test_native_capture.py`

- [ ] **Step 1: Write failing tests for screenshot paths**

Create `backend/tests/test_native_capture.py`:

```python
from pathlib import Path

from agent.computer_use.native_windows import capture


class FakeImage:
    def __init__(self):
        self.saved_to = None

    def save(self, path):
        self.saved_to = Path(path)
        Path(path).write_bytes(b"fake-png")


def test_screenshot_filename_is_sanitized(tmp_path):
    fake = FakeImage()

    result = capture.save_window_screenshot(
        100,
        screenshot_dir=tmp_path,
        filename="../bad name.png",
        image_factory=lambda hwnd: fake,
    )

    assert result["path"].endswith("bad_name.png")
    assert fake.saved_to.name == "bad_name.png"


def test_default_screenshot_filename_mentions_hwnd(tmp_path):
    fake = FakeImage()

    result = capture.save_window_screenshot(100, screenshot_dir=tmp_path, image_factory=lambda hwnd: fake)

    assert "window-100-" in Path(result["path"]).name
    assert result["hwnd"] == 100
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_native_capture.py -v
```

Expected: import error for `capture`.

- [ ] **Step 3: Implement native capture wrapper**

Create `backend/agent/computer_use/native_windows/capture.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Callable

from agent.config import get_settings


def save_window_screenshot(
    hwnd: int,
    *,
    screenshot_dir: Path | None = None,
    filename: str | None = None,
    image_factory: Callable[[int], Any] | None = None,
) -> dict[str, Any]:
    directory = screenshot_dir or get_settings().computer_use_screenshot_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _filename(hwnd, filename)
    image = (image_factory or capture_window_image)(int(hwnd))
    image.save(path)
    return {"hwnd": int(hwnd), "path": str(path), "width": getattr(image, "width", None), "height": getattr(image, "height", None)}


def capture_window_image(hwnd: int):
    if not hasattr(__import__("ctypes"), "windll"):
        raise RuntimeError("Native window capture requires Windows.")
    return _capture_with_print_window(hwnd)


def _filename(hwnd: int, filename: str | None) -> str:
    raw = str(filename or "").strip()
    if not raw:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        raw = f"window-{int(hwnd)}-{stamp}.png"
    name = raw.replace("\\", "/").split("/")[-1]
    if not name.casefold().endswith(".png"):
        name = f"{name}.png"
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _capture_with_print_window(hwnd: int):
    import ctypes
    from ctypes import wintypes
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("GetWindowRect failed.")
    width = max(1, rect.right - rect.left)
    height = max(1, rect.bottom - rect.top)
    hdc_window = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
    gdi32.SelectObject(hdc_mem, hbmp)
    try:
        user32.PrintWindow(hwnd, hdc_mem, 2)
        bitmap_info = _bitmap_info(width, height)
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(hdc_mem, hbmp, 0, height, buffer, ctypes.byref(bitmap_info), 0)
        return Image.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1)
    finally:
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)


def _bitmap_info(width: int, height: int):
    import ctypes
    from ctypes import wintypes

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    return info
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_native_capture.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit and push**

Run:

```powershell
git add backend/agent/computer_use/native_windows/capture.py backend/tests/test_native_capture.py
git commit -m "feat: add native window screenshot capture"
git push origin native-windows-computer-use
```

---

### Task 5: SendInput Actions

**Files:**
- Create: `backend/agent/computer_use/native_windows/input.py`
- Create: `backend/tests/test_native_input.py`

- [ ] **Step 1: Write failing tests for action helpers**

Create `backend/tests/test_native_input.py`:

```python
from agent.computer_use.native_windows import input as native_input


def test_click_sends_move_down_up():
    calls = []

    native_input.click(10, 20, sender=lambda event: calls.append(event))

    assert calls == [
        {"kind": "move", "x": 10, "y": 20},
        {"kind": "mouse_down", "button": "left"},
        {"kind": "mouse_up", "button": "left"},
    ]


def test_type_text_sends_each_character():
    calls = []

    native_input.type_text("Hi", sender=lambda event: calls.append(event))

    assert calls == [{"kind": "text", "text": "H"}, {"kind": "text", "text": "i"}]


def test_hotkey_splits_plus_separated_keys():
    calls = []

    native_input.press_key("ctrl+shift+tab", sender=lambda event: calls.append(event))

    assert calls == [{"kind": "hotkey", "keys": ["ctrl", "shift", "tab"]}]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_native_input.py -v
```

Expected: import error for `native_windows.input`.

- [ ] **Step 3: Implement testable action helpers with SendInput fallback point**

Create `backend/agent/computer_use/native_windows/input.py`:

```python
from __future__ import annotations

from typing import Any, Callable


Sender = Callable[[dict[str, Any]], None]


def click(x: int, y: int, *, button: str = "left", click_count: int = 1, sender: Sender | None = None) -> None:
    emit = sender or _send_event
    emit({"kind": "move", "x": int(x), "y": int(y)})
    for _ in range(max(1, int(click_count))):
        emit({"kind": "mouse_down", "button": _button(button)})
        emit({"kind": "mouse_up", "button": _button(button)})


def type_text(text: str, *, sender: Sender | None = None) -> None:
    emit = sender or _send_event
    for char in str(text):
        emit({"kind": "text", "text": char})


def press_key(key: str, *, sender: Sender | None = None) -> None:
    emit = sender or _send_event
    keys = [part.strip().casefold() for part in str(key).replace("+", ",").split(",") if part.strip()]
    if not keys:
        raise ValueError("press_key requires key.")
    if len(keys) > 1:
        emit({"kind": "hotkey", "keys": keys})
    else:
        emit({"kind": "key", "key": keys[0]})


def scroll(x: int, y: int, *, scroll_x: int = 0, scroll_y: int = 0, sender: Sender | None = None) -> None:
    emit = sender or _send_event
    emit({"kind": "move", "x": int(x), "y": int(y)})
    emit({"kind": "scroll", "scroll_x": int(scroll_x), "scroll_y": int(scroll_y)})


def drag(from_x: int, from_y: int, to_x: int, to_y: int, *, sender: Sender | None = None) -> None:
    emit = sender or _send_event
    emit({"kind": "move", "x": int(from_x), "y": int(from_y)})
    emit({"kind": "mouse_down", "button": "left"})
    emit({"kind": "move", "x": int(to_x), "y": int(to_y)})
    emit({"kind": "mouse_up", "button": "left"})


def _button(button: str) -> str:
    value = str(button or "left").casefold()
    if value not in {"left", "right", "middle"}:
        raise ValueError("Mouse button must be left, right, or middle.")
    return value


def _send_event(event: dict[str, Any]) -> None:
    if event["kind"] == "text":
        _send_text(event["text"])
        return
    if event["kind"] == "key":
        _send_key(event["key"])
        return
    if event["kind"] == "hotkey":
        for key in event["keys"]:
            _send_key_down(key)
        for key in reversed(event["keys"]):
            _send_key_up(key)
        return
    _send_mouse_event(event)


def _send_text(text: str) -> None:
    import ctypes
    for char in text:
        code = ord(char)
        _send_keyboard_input(code, 0x0004)
        _send_keyboard_input(code, 0x0004 | 0x0002)


def _send_key(key: str) -> None:
    _send_key_down(key)
    _send_key_up(key)


def _send_key_down(key: str) -> None:
    vk = _virtual_key(key)
    _send_keyboard_input(vk, 0)


def _send_key_up(key: str) -> None:
    vk = _virtual_key(key)
    _send_keyboard_input(vk, 0x0002)


def _send_mouse_event(event: dict[str, Any]) -> None:
    import ctypes
    user32 = ctypes.windll.user32
    kind = event["kind"]
    if kind == "move":
        user32.SetCursorPos(int(event["x"]), int(event["y"]))
        return
    if kind == "mouse_down":
        _send_mouse_input(_mouse_flag(event["button"], down=True))
        return
    if kind == "mouse_up":
        _send_mouse_input(_mouse_flag(event["button"], down=False))
        return
    if kind == "scroll":
        if int(event.get("scroll_y") or 0):
            _send_mouse_input(0x0800, data=int(event["scroll_y"]) * 120)
        if int(event.get("scroll_x") or 0):
            _send_mouse_input(0x1000, data=int(event["scroll_x"]) * 120)
        return
    raise ValueError(f"Unsupported mouse event: {kind}")


def _virtual_key(key: str) -> int:
    mapping = {
        "ctrl": 0x11,
        "control": 0x11,
        "shift": 0x10,
        "alt": 0x12,
        "tab": 0x09,
        "enter": 0x0D,
        "return": 0x0D,
        "esc": 0x1B,
        "escape": 0x1B,
        "backspace": 0x08,
        "delete": 0x2E,
        "space": 0x20,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
        "pageup": 0x21,
        "pagedown": 0x22,
        "home": 0x24,
        "end": 0x23,
    }
    normalized = key.strip().casefold()
    if normalized in mapping:
        return mapping[normalized]
    if len(normalized) == 1:
        return ord(normalized.upper())
    raise ValueError(f"Unsupported key: {key}")


def _mouse_flag(button: str, *, down: bool) -> int:
    flags = {
        ("left", True): 0x0002,
        ("left", False): 0x0004,
        ("right", True): 0x0008,
        ("right", False): 0x0010,
        ("middle", True): 0x0020,
        ("middle", False): 0x0040,
    }
    return flags[(_button(button), down)]


def _send_keyboard_input(code: int, flags: int) -> None:
    import ctypes
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]

    item = INPUT()
    item.type = 1
    if flags & 0x0004:
        item.union.ki = KEYBDINPUT(0, int(code), flags, 0, 0)
    else:
        item.union.ki = KEYBDINPUT(int(code), 0, flags, 0, 0)
    sent = ctypes.windll.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))
    if sent != 1:
        raise RuntimeError("SendInput keyboard event failed.")


def _send_mouse_input(flags: int, *, data: int = 0) -> None:
    import ctypes
    from ctypes import wintypes

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]

    item = INPUT()
    item.type = 0
    item.union.mi = MOUSEINPUT(0, 0, int(data), int(flags), 0, 0)
    sent = ctypes.windll.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))
    if sent != 1:
        raise RuntimeError("SendInput mouse event failed.")
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_native_input.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit and push**

Run:

```powershell
git add backend/agent/computer_use/native_windows/input.py backend/tests/test_native_input.py
git commit -m "feat: add native input action helpers"
git push origin native-windows-computer-use
```

---

### Task 6: Native Driver Assembly

**Files:**
- Create: `backend/agent/computer_use/native_windows/driver.py`
- Modify: `backend/agent/computer_use/windows_driver.py`
- Modify: `backend/agent/computer_use/router.py`
- Create: `backend/tests/test_native_driver.py`
- Modify: `backend/tests/test_computer_use_driver.py`
- Modify: `backend/tests/test_computer_use_router.py`

- [ ] **Step 1: Write failing native driver tests**

Create `backend/tests/test_native_driver.py`:

```python
from agent.computer_use.native_windows.driver import WindowsNativeComputerDriver


class FakeWindowing:
    def __init__(self):
        self.activated = []

    def list_windows(self):
        from agent.computer_use.operator import ComputerWindow
        return [ComputerWindow("hwnd:1", 1, "notepad.exe", 2, "Untitled - Notepad", {"x": 0, "y": 0, "width": 100, "height": 80})]

    def get_window(self, window_id):
        return self.list_windows()[0]

    def active_window(self):
        return self.list_windows()[0]

    def activate_window(self, window_id):
        self.activated.append(window_id)
        return self.list_windows()[0]


class FakeAccessibility:
    def get_accessibility_state(self, hwnd, include_text=True):
        return {"tree": "[0] Window name='Notepad'", "elements": [{"index": 0, "bounds": {"x": 10, "y": 20, "width": 30, "height": 40}}]}

    def element_center(self, state, index):
        return (25, 40)


class FakeCapture:
    def save_window_screenshot(self, hwnd, **kwargs):
        return {"path": "screen.png", "hwnd": hwnd}


class FakeInput:
    def __init__(self):
        self.calls = []

    def click(self, x, y, **kwargs):
        self.calls.append(("click", x, y, kwargs))


def test_driver_observe_returns_window_screenshot_and_accessibility():
    driver = WindowsNativeComputerDriver(windowing=FakeWindowing(), accessibility=FakeAccessibility(), capture=FakeCapture(), input_layer=FakeInput())

    result = driver.get_window_state("hwnd:1")

    assert result.status == "ok"
    assert result.backend == "windows_native"
    assert result.observation["window"]["id"] == "hwnd:1"
    assert result.observation["screenshot"]["path"] == "screen.png"
    assert "Notepad" in result.observation["accessibility"]["tree"]


def test_driver_click_element_activates_window_and_uses_element_center():
    windowing = FakeWindowing()
    input_layer = FakeInput()
    driver = WindowsNativeComputerDriver(windowing=windowing, accessibility=FakeAccessibility(), capture=FakeCapture(), input_layer=input_layer)

    result = driver.click("hwnd:1", element_index=0)

    assert result.status == "ok"
    assert windowing.activated == ["hwnd:1"]
    assert input_layer.calls[0][0:3] == ("click", 25, 40)
    assert result.observation is not None
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_native_driver.py -v
```

Expected: import error for `native_windows.driver`.

- [ ] **Step 3: Implement native driver composition**

Create `backend/agent/computer_use/native_windows/driver.py`:

```python
from __future__ import annotations

from typing import Any

from agent.computer_use.operator import OperatorResult
from agent.computer_use.native_windows import accessibility as default_accessibility
from agent.computer_use.native_windows import capture as default_capture
from agent.computer_use.native_windows import input as default_input
from agent.computer_use.native_windows import windowing as default_windowing


class WindowsNativeComputerDriver:
    backend = "windows_native"

    def __init__(self, *, windowing=default_windowing, accessibility=default_accessibility, capture=default_capture, input_layer=default_input) -> None:
        self.windowing = windowing
        self.accessibility = accessibility
        self.capture = capture
        self.input = input_layer

    def health_check(self) -> dict[str, Any]:
        try:
            windows = self.windowing.list_windows()
        except Exception as exc:
            return {"ok": False, "backend": self.backend, "message": str(exc)}
        return {"ok": True, "backend": self.backend, "message": f"{len(windows)} targetable windows found."}

    def list_apps(self) -> OperatorResult:
        windows = self.windowing.list_windows()
        apps = sorted({window.app for window in windows})
        return OperatorResult("ok", self.backend, f"{len(apps)} apps found.", {"apps": apps})

    def list_windows(self) -> OperatorResult:
        windows = [window.to_dict() for window in self.windowing.list_windows()]
        return OperatorResult("ok", self.backend, f"{len(windows)} windows found.", {"windows": windows})

    def get_window_state(self, window_id: str | None = None, *, include_screenshot: bool = True, include_text: bool = True) -> OperatorResult:
        window = self.windowing.get_window(window_id) if window_id else self.windowing.active_window()
        accessibility_state = self.accessibility.get_accessibility_state(window.hwnd, include_text=include_text)
        screenshot = self.capture.save_window_screenshot(window.hwnd) if include_screenshot else None
        observation = {"window": window.to_dict(), "accessibility": accessibility_state}
        if screenshot is not None:
            observation["screenshot"] = screenshot
        return OperatorResult("ok", self.backend, "Window observed.", {"window_id": window.id}, observation)

    def activate_window(self, window_id: str) -> OperatorResult:
        window = self.windowing.activate_window(window_id)
        return OperatorResult("ok", self.backend, f"Activated {window.title}.", {"window": window.to_dict()})

    def click(self, window_id: str | None = None, *, element_index: int | None = None, x: int | None = None, y: int | None = None, button: str = "left", click_count: int = 1) -> OperatorResult:
        window = self.windowing.activate_window(window_id) if window_id else self.windowing.active_window()
        if element_index is not None:
            state = self.accessibility.get_accessibility_state(window.hwnd, include_text=True)
            x, y = self.accessibility.element_center(state, int(element_index))
        if x is None or y is None:
            raise ValueError("Native click requires element_index or x/y coordinates.")
        self.input.click(int(x), int(y), button=button, click_count=click_count)
        observation = self.get_window_state(window.id).observation
        return OperatorResult("ok", self.backend, f"Clicked at {int(x)},{int(y)}.", {"window_id": window.id, "x": int(x), "y": int(y)}, observation)

    def type_text(self, text: str, window_id: str | None = None) -> OperatorResult:
        window = self.windowing.activate_window(window_id) if window_id else self.windowing.active_window()
        self.input.type_text(text)
        observation = self.get_window_state(window.id).observation
        return OperatorResult("ok", self.backend, "Typed text.", {"window_id": window.id}, observation)

    def press_key(self, key: str, window_id: str | None = None) -> OperatorResult:
        window = self.windowing.activate_window(window_id) if window_id else self.windowing.active_window()
        self.input.press_key(key)
        observation = self.get_window_state(window.id).observation
        return OperatorResult("ok", self.backend, f"Pressed key: {key}.", {"window_id": window.id, "key": key}, observation)

    def scroll(self, window_id: str | None = None, *, x: int = 0, y: int = 0, scroll_x: int = 0, scroll_y: int = 0) -> OperatorResult:
        window = self.windowing.activate_window(window_id) if window_id else self.windowing.active_window()
        self.input.scroll(x, y, scroll_x=scroll_x, scroll_y=scroll_y)
        observation = self.get_window_state(window.id).observation
        return OperatorResult("ok", self.backend, "Scrolled.", {"window_id": window.id}, observation)

    def drag(self, window_id: str | None = None, *, from_x: int, from_y: int, to_x: int, to_y: int) -> OperatorResult:
        window = self.windowing.activate_window(window_id) if window_id else self.windowing.active_window()
        self.input.drag(from_x, from_y, to_x, to_y)
        observation = self.get_window_state(window.id).observation
        return OperatorResult("ok", self.backend, "Dragged.", {"window_id": window.id}, observation)
```

- [ ] **Step 4: Update `WindowsComputerDriver` to delegate native structured actions**

Modify `backend/agent/computer_use/windows_driver.py` so it imports `WindowsNativeComputerDriver`, creates one in `__init__`, and maps existing `run_action(action, **params)` calls to native methods. For unsupported legacy actions, return `{"status": "unsupported", "message": "Unsupported native desktop action: <action>"}` instead of calling `agent.tools.desktop`.

- [ ] **Step 5: Run tests**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_native_driver.py tests/test_computer_use_driver.py tests/test_computer_use_router.py -v
```

Expected: native driver tests pass; update legacy expectations so they assert native backend results instead of `desktop_tools.run_desktop_action` calls.

- [ ] **Step 6: Commit and push**

Run:

```powershell
git add backend/agent/computer_use/native_windows/driver.py backend/agent/computer_use/windows_driver.py backend/agent/computer_use/router.py backend/tests/test_native_driver.py backend/tests/test_computer_use_driver.py backend/tests/test_computer_use_router.py
git commit -m "feat: route desktop computer use to native driver"
git push origin native-windows-computer-use
```

---

### Task 7: Transparent Blue Edge-Glow Overlay With Esc Exit

**Files:**
- Create: `backend/agent/computer_use/native_windows/overlay.py`
- Modify: `backend/agent/computer_use/overlay.py`
- Modify: `backend/agent/computer_use/session.py`
- Modify: `backend/tests/test_computer_use_session.py`

- [ ] **Step 1: Write failing overlay/session tests**

Add to `backend/tests/test_computer_use_session.py`:

```python
def test_session_overlay_interrupt_stops_computer_use(tmp_path):
    from agent.computer_use.session import ComputerUseSession

    overlay = FakeOverlay()
    guard = FakeInputGuard()
    runtime = _runtime(tmp_path)
    session = ComputerUseSession(runtime=runtime, overlay=overlay, router=FakeRouter(), input_guard=guard)
    session.start(source="ui", thread_id="frontend")

    session._handle_overlay_interrupt("esc")

    assert runtime.status()["enabled"] is False
    assert runtime.status()["source"] == "overlay"
    assert overlay.calls == ["start", "stop"]
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_computer_use_session.py::test_session_overlay_interrupt_stops_computer_use -v
```

Expected: `ComputerUseSession` has no `_handle_overlay_interrupt`.

- [ ] **Step 3: Implement native overlay controller**

Create `backend/agent/computer_use/native_windows/overlay.py` with a backend process that opens a borderless topmost transparent overlay, uses click-through window styles, and exits on Esc. It should expose `start()`, `stop()`, `status()`, and `set_interrupt_callback(callback)` methods. Use the existing Tkinter process approach from `agent.tools.desktop` as the practical foundation, but move it into this native module and change the visual/copy to a blue edge glow plus a small top-center status pill:

```python
MESSAGE = "Vellum is using your computer  ·  Esc to cancel"
ACCENT = "#0b5fff"
```

The subprocess should write a small sentinel file or exit code when Esc is pressed so the parent can call the session interrupt callback.

- [ ] **Step 4: Wire overlay interrupt into session**

Modify `ComputerUseSession` to include:

```python
def _handle_overlay_interrupt(self, reason: str) -> None:
    state = self.runtime.status()
    if not state.get("enabled"):
        return
    self.stop(source="overlay", reason=reason)
```

If the overlay controller supports `set_interrupt_callback`, call it during `start()` before `overlay.start()`.

- [ ] **Step 5: Run session tests**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_computer_use_session.py tests/test_api.py -k "computer_use" -v
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit and push**

Run:

```powershell
git add backend/agent/computer_use/native_windows/overlay.py backend/agent/computer_use/overlay.py backend/agent/computer_use/session.py backend/tests/test_computer_use_session.py
git commit -m "feat: add native computer use overlay"
git push origin native-windows-computer-use
```

---

### Task 8: Public Tool Routing And Expanded Desktop Actions

**Files:**
- Modify: `backend/agent/tools/computer_use.py`
- Modify: `backend/agent/graph/agent.py`
- Modify: `backend/tests/test_computer_use.py`
- Modify: `backend/tests/test_agent_prompt.py`

- [ ] **Step 1: Update tests for native desktop actions**

Modify `backend/tests/test_computer_use.py` so desktop tests monkeypatch `computer_use_tools.WindowsComputerDriver` or the module-level native driver instead of `desktop_tools.run_desktop_action`. Add tests for:

```python
def test_computer_use_routes_desktop_observe_to_native_driver(monkeypatch):
    calls = []

    class FakeDriver:
        def run_action(self, action, **params):
            calls.append((action, params))
            return {"status": "ok", "message": "observed", "backend": "windows_native"}

    monkeypatch.setattr(computer_use_tools, "desktop_driver", FakeDriver())

    result = computer_use_tools.computer_use.invoke({"mode": "desktop", "action": "observe", "target": "hwnd:1"})

    assert result == "observed"
    assert calls == [("observe", {"target": "hwnd:1"})]
```

Add similar tests for `list_windows`, `click` with `element_index`, and `type`.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_computer_use.py -k "desktop" -v
```

Expected: tests fail because the public tool still calls `desktop_tools`.

- [ ] **Step 3: Route desktop mode to native driver**

Modify `backend/agent/tools/computer_use.py`:

- remove `from agent.tools import desktop as desktop_tools`
- import `WindowsComputerDriver`
- create `desktop_driver = WindowsComputerDriver()`
- make desktop mode call `desktop_driver.run_action(action, **params)`
- convert structured native results to the existing string return by returning `result["message"]`
- keep runtime events and redaction logic
- keep permission/mode/input-guard gates before mutating actions

- [ ] **Step 4: Update agent prompt**

Modify `backend/agent/graph/agent.py` so the computer-use prompt says native desktop mode supports `list_windows`, `observe`, target window ids, accessibility element indexes, and the blue Esc overlay.

- [ ] **Step 5: Run tests**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_computer_use.py tests/test_agent_prompt.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit and push**

Run:

```powershell
git add backend/agent/tools/computer_use.py backend/agent/graph/agent.py backend/tests/test_computer_use.py backend/tests/test_agent_prompt.py
git commit -m "feat: expose native desktop computer use tool"
git push origin native-windows-computer-use
```

---

### Task 9: Remove PyAutoGUI Dependency And Legacy Desktop Path

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/pyproject.toml`
- Modify: `backend/agent/tools/desktop.py`
- Modify: `backend/tests/test_computer_use.py`
- Modify: `backend/tests/test_config.py`

- [ ] **Step 1: Write dependency assertion test**

Add to `backend/tests/test_config.py`:

```python
def test_pyautogui_removed_from_dependency_files():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert "pyautogui" not in (root / "requirements.txt").read_text(encoding="utf-8").casefold()
    assert "pyautogui" not in (root / "pyproject.toml").read_text(encoding="utf-8").casefold()
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_config.py::test_pyautogui_removed_from_dependency_files -v
```

Expected: fail because dependency files still mention `pyautogui`.

- [ ] **Step 3: Remove dependency and legacy imports**

Edit:

- remove `pyautogui>=0.9.54` from `backend/requirements.txt`
- remove `"pyautogui>=0.9.54",` from `backend/pyproject.toml`
- add `comtypes>=1.4.0; platform_system == "Windows"` to both dependency files
- add `psutil>=6.0.0` to `backend/requirements.txt` to match `pyproject.toml`
- delete or shrink `backend/agent/tools/desktop.py` into a compatibility shim that raises/returns `Desktop computer use has moved to the native Windows driver. Use agent.computer_use.windows_driver.WindowsComputerDriver.`

- [ ] **Step 4: Update tests away from fake pyautogui**

Remove old `FakePyAutoGui` tests from `backend/tests/test_computer_use.py` or rewrite them against native driver fakes. No test should import or monkeypatch `_pyautogui`.

- [ ] **Step 5: Run dependency/config tests**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_computer_use.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit and push**

Run:

```powershell
git add backend/requirements.txt backend/pyproject.toml backend/agent/tools/desktop.py backend/tests/test_computer_use.py backend/tests/test_config.py
git commit -m "chore: remove pyautogui desktop backend"
git push origin native-windows-computer-use
```

---

### Task 10: Verification And Manual Windows Smoke Test

**Files:**
- Modify only if verification reveals small fixes.

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_computer_use_operator.py tests/test_native_windowing.py tests/test_native_accessibility.py tests/test_native_capture.py tests/test_native_input.py tests/test_native_driver.py tests/test_computer_use_driver.py tests/test_computer_use_router.py tests/test_computer_use_session.py tests/test_computer_use.py tests/test_agent_prompt.py tests/test_config.py tests/test_api.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Run a dependency grep**

Run:

```powershell
rg -n "pyautogui|_pyautogui|FakePyAutoGui" backend
```

Expected: no matches, except historical docs if those are intentionally left unchanged. Production code and tests must have no matches.

- [ ] **Step 3: Manual native smoke test**

Start the backend and use the agent/tool manually to verify:

```text
computer_use(mode="desktop", action="list_windows")
computer_use(mode="desktop", action="observe")
computer_use(mode="desktop", action="open_app", app="notepad")
computer_use(mode="desktop", action="type", text="hello from vellum")
computer_use(mode="desktop", action="press_key", key="ctrl+a")
computer_use(mode="desktop", action="switch_browser_tab", tab_action="next")
```

Expected:

- blue overlay appears while native session is active
- Esc exits the session and removes the overlay
- list/observe return native backend provenance
- Notepad receives typed text only after focus is established
- screenshots are saved under `data/computer-use/screenshots`

- [ ] **Step 4: Commit and push any verification fixes**

If fixes were needed:

```powershell
git add <fixed files>
git commit -m "fix: stabilize native computer use verification"
git push origin native-windows-computer-use
```

If no fixes were needed, do not create an empty commit.

---

## Plan Self-Review

- Spec coverage: native Win32 windowing, UIA accessibility, native capture, SendInput, blue Esc overlay, existing safety gates, Playwright retention, Codex fallback adapter, and pyautogui removal are each represented by tasks.
- Placeholder scan: no TBD/TODO placeholders remain; every task has concrete file paths, commands, and expected results.
- Type consistency: `ComputerWindow`, `OperatorResult`, `WindowsNativeComputerDriver`, and action method names are consistent across tasks.
- Scope check: the plan only covers native Windows computer use and its direct routing/dependency migration. It does not implement broader sub-agent architecture.
