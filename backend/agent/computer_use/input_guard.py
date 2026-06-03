"""Exclusive host input guard for computer-use sessions."""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Protocol

from agent.config import get_settings


InterruptCallback = Callable[[str], None]
LRESULT = ctypes.c_ssize_t
WPARAM = wintypes.WPARAM
LPARAM = wintypes.LPARAM
HHOOK = wintypes.HANDLE


class InputGuard(Protocol):
    def acquire(self, *, session_id: str, on_interrupt: InterruptCallback) -> str:
        """Acquire exclusive user-input control."""

    def release(self) -> str:
        """Release exclusive user-input control."""

    def heartbeat(self) -> None:
        """Mark the controlling process as alive."""

    def status(self) -> dict[str, object]:
        """Return guard status."""


@dataclass
class NoopInputGuard:
    reason: str = "exclusive control disabled"

    def acquire(self, *, session_id: str, on_interrupt: InterruptCallback) -> str:
        return self.reason

    def release(self) -> str:
        return "input guard inactive"

    def heartbeat(self) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {
            "ready": True,
            "active": False,
            "lease_active": True,
            "exclusive": False,
            "kind": "noop",
            "kill_switch": "not required",
            "reason": self.reason,
        }


class WindowsInputGuard:
    """Block physical keyboard/mouse input while allowing synthetic automation.

    The guard installs low-level Windows hooks. Physical keyboard/mouse events
    are swallowed; injected events from automation libraries are allowed. The
    emergency kill switch is Ctrl+Alt+Esc.
    """

    WH_KEYBOARD_LL = 13
    WH_MOUSE_LL = 14
    WM_QUIT = 0x0012
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104
    VK_ESCAPE = 0x1B
    VK_CONTROL = 0x11
    VK_MENU = 0x12
    LLKHF_INJECTED = 0x10
    LLMHF_INJECTED = 0x01

    def __init__(self, *, watchdog_seconds: float = 300.0) -> None:
        self.watchdog_seconds = max(5.0, float(watchdog_seconds))
        self._lock = threading.RLock()
        self._active = False
        self._session_id = ""
        self._on_interrupt: InterruptCallback | None = None
        self._last_heartbeat = 0.0
        self._thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._thread_id = 0
        self._keyboard_hook = None
        self._mouse_hook = None
        self._keyboard_proc = None
        self._mouse_proc = None
        self._last_interrupt = ""

    def acquire(self, *, session_id: str, on_interrupt: InterruptCallback) -> str:
        if os.name != "nt":
            raise RuntimeError("exclusive input guard is only available on Windows")
        with self._lock:
            if self._active:
                self._session_id = session_id
                self._on_interrupt = on_interrupt
                self.heartbeat()
                return "input guard already active"
            self._session_id = session_id
            self._on_interrupt = on_interrupt
            self._last_interrupt = ""
            self._last_heartbeat = time.monotonic()
            ready = threading.Event()
            error: list[BaseException] = []
            self._thread = threading.Thread(target=self._message_loop, args=(ready, error), daemon=True)
            self._thread.start()
        if not ready.wait(timeout=4):
            self.release()
            raise RuntimeError("input guard did not become ready")
        if error:
            self.release()
            raise RuntimeError(str(error[0]))
        with self._lock:
            self._active = True
            self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            self._watchdog_thread.start()
        return "exclusive input guard active; Ctrl+Alt+Esc stops computer use"

    def release(self) -> str:
        with self._lock:
            was_active = self._active
            self._active = False
            thread = self._thread
            thread_id = self._thread_id
            self._thread = None
        try:
            if os.name == "nt" and thread_id:
                ctypes.windll.user32.PostThreadMessageW(thread_id, self.WM_QUIT, 0, 0)
        except Exception:
            pass
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        return "input guard released" if was_active else "input guard inactive"

    def heartbeat(self) -> None:
        with self._lock:
            self._last_heartbeat = time.monotonic()

    def status(self) -> dict[str, object]:
        with self._lock:
            active = self._active
            last_heartbeat = self._last_heartbeat
            session_id = self._session_id
            last_interrupt = self._last_interrupt
        age = max(0.0, time.monotonic() - last_heartbeat) if last_heartbeat else None
        return {
            "ready": os.name == "nt",
            "active": active,
            "lease_active": active,
            "exclusive": True,
            "kind": "windows-hook",
            "session_id": session_id,
            "kill_switch": "Ctrl+Alt+Esc",
            "watchdog_seconds": self.watchdog_seconds,
            "heartbeat_age_seconds": age,
            "last_interrupt": last_interrupt,
        }

    def _watchdog_loop(self) -> None:
        while True:
            time.sleep(1)
            with self._lock:
                if not self._active:
                    return
                expired = time.monotonic() - self._last_heartbeat > self.watchdog_seconds
            if expired:
                self._trigger_interrupt("input guard watchdog expired")
                return

    def _message_loop(self, ready: threading.Event, error: list[BaseException]) -> None:
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            self._configure_hook_api(user32)
            self._thread_id = kernel32.GetCurrentThreadId()
            low_level_proc = self._low_level_proc_type()
            self._keyboard_proc = low_level_proc(self._keyboard_callback)
            self._mouse_proc = low_level_proc(self._mouse_callback)
            self._keyboard_hook = user32.SetWindowsHookExW(self.WH_KEYBOARD_LL, self._keyboard_proc, None, 0)
            self._mouse_hook = user32.SetWindowsHookExW(self.WH_MOUSE_LL, self._mouse_proc, None, 0)
            if not self._keyboard_hook or not self._mouse_hook:
                raise ctypes.WinError()
            ready.set()
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except BaseException as exc:
            error.append(exc)
            ready.set()
        finally:
            self._unhook()

    def _keyboard_callback(self, n_code, w_param, l_param):
        user32 = ctypes.windll.user32
        if n_code < 0:
            return self._call_next_hook(user32, self._keyboard_hook, n_code, w_param, l_param)
        event = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        if event.flags & self.LLKHF_INJECTED:
            return self._call_next_hook(user32, self._keyboard_hook, n_code, w_param, l_param)
        if int(w_param) in {self.WM_KEYDOWN, self.WM_SYSKEYDOWN} and event.vkCode == self.VK_ESCAPE:
            ctrl = user32.GetAsyncKeyState(self.VK_CONTROL) & 0x8000
            alt = user32.GetAsyncKeyState(self.VK_MENU) & 0x8000
            if ctrl and alt:
                self._trigger_interrupt("kill switch")
                return 1
        return 1

    def _mouse_callback(self, n_code, w_param, l_param):
        user32 = ctypes.windll.user32
        if n_code < 0:
            return self._call_next_hook(user32, self._mouse_hook, n_code, w_param, l_param)
        event = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
        if event.flags & self.LLMHF_INJECTED:
            return self._call_next_hook(user32, self._mouse_hook, n_code, w_param, l_param)
        return 1

    @staticmethod
    def _low_level_proc_type():
        return ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)

    @staticmethod
    def _configure_hook_api(user32) -> None:
        user32.CallNextHookEx.argtypes = [HHOOK, ctypes.c_int, WPARAM, LPARAM]
        user32.CallNextHookEx.restype = LRESULT
        user32.SetWindowsHookExW.restype = HHOOK
        user32.UnhookWindowsHookEx.argtypes = [HHOOK]

    @staticmethod
    def _call_next_hook(user32, hook, n_code, w_param, l_param):
        return user32.CallNextHookEx(
            WindowsInputGuard._coerce_ctype(HHOOK, hook),
            WindowsInputGuard._coerce_ctype(ctypes.c_int, n_code),
            WindowsInputGuard._coerce_ctype(WPARAM, w_param),
            WindowsInputGuard._coerce_ctype(LPARAM, l_param),
        )

    @staticmethod
    def _coerce_ctype(ctype, value):
        if isinstance(value, ctype):
            return value
        return ctype(value.value if hasattr(value, "value") else value)

    def _trigger_interrupt(self, reason: str) -> None:
        with self._lock:
            if not self._active:
                return
            self._last_interrupt = reason
            callback = self._on_interrupt
        self.release()
        if callback is not None:
            threading.Thread(target=callback, args=(reason,), daemon=True).start()

    def _unhook(self) -> None:
        if os.name != "nt":
            return
        user32 = ctypes.windll.user32
        if self._keyboard_hook:
            user32.UnhookWindowsHookEx(self._keyboard_hook)
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
        self._keyboard_hook = None
        self._mouse_hook = None


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


def build_input_guard() -> InputGuard:
    settings = get_settings()
    if not settings.computer_use_exclusive_control:
        return NoopInputGuard()
    if os.name != "nt":
        return NoopInputGuard(reason="exclusive control is only available on Windows")
    return WindowsInputGuard(watchdog_seconds=settings.computer_use_guard_watchdog_seconds)


computer_use_input_guard = build_input_guard()
