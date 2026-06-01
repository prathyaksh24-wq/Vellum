from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Callable

Sender = Callable[[dict[str, Any]], None]

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
WHEEL_DELTA = 120

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _INPUTUNION),
    ]


_configured_user32_ids: set[int] = set()

_BUTTON_FLAGS = {
    ("left", "down"): MOUSEEVENTF_LEFTDOWN,
    ("left", "up"): MOUSEEVENTF_LEFTUP,
    ("right", "down"): MOUSEEVENTF_RIGHTDOWN,
    ("right", "up"): MOUSEEVENTF_RIGHTUP,
    ("middle", "down"): MOUSEEVENTF_MIDDLEDOWN,
    ("middle", "up"): MOUSEEVENTF_MIDDLEUP,
}

_VK_KEYS = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "caps_lock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "page_up": 0x21,
    "pagedown": 0x22,
    "page_down": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "win": 0x5B,
    "windows": 0x5B,
    "cmd": 0x5B,
    "meta": 0x5B,
    "numpad0": 0x60,
    "numpad1": 0x61,
    "numpad2": 0x62,
    "numpad3": 0x63,
    "numpad4": 0x64,
    "numpad5": 0x65,
    "numpad6": 0x66,
    "numpad7": 0x67,
    "numpad8": 0x68,
    "numpad9": 0x69,
    "multiply": 0x6A,
    "add": 0x6B,
    "subtract": 0x6D,
    "decimal": 0x6E,
    "divide": 0x6F,
    "numlock": 0x90,
    "scrolllock": 0x91,
}
_VK_KEYS.update({f"f{number}": 0x6F + number for number in range(1, 25)})


def click(
    x: int,
    y: int,
    *,
    button: str = "left",
    click_count: int = 1,
    sender: Sender | None = None,
) -> None:
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
    keys = [
        part.strip().casefold()
        for part in str(key).replace("+", ",").split(",")
        if part.strip()
    ]
    if not keys:
        raise ValueError("press_key requires key.")
    if len(keys) > 1:
        emit({"kind": "hotkey", "keys": keys})
    else:
        emit({"kind": "key", "key": keys[0]})


def scroll(
    x: int,
    y: int,
    *,
    scroll_x: int = 0,
    scroll_y: int = 0,
    sender: Sender | None = None,
) -> None:
    emit = sender or _send_event
    emit({"kind": "move", "x": int(x), "y": int(y)})
    emit({"kind": "scroll", "scroll_x": int(scroll_x), "scroll_y": int(scroll_y)})


def drag(
    from_x: int,
    from_y: int,
    to_x: int,
    to_y: int,
    *,
    sender: Sender | None = None,
) -> None:
    emit = sender or _send_event
    emit({"kind": "move", "x": int(from_x), "y": int(from_y)})
    emit({"kind": "mouse_down", "button": "left"})
    emit({"kind": "move", "x": int(to_x), "y": int(to_y)})
    emit({"kind": "mouse_up", "button": "left"})


def _button(button: str) -> str:
    normalized = str(button).strip().casefold()
    if normalized not in {"left", "right", "middle"}:
        raise ValueError(f"Unsupported mouse button: {button}")
    return normalized


def _send_event(event: dict[str, Any]) -> None:
    kind = event.get("kind")
    if kind == "move":
        user32 = _user32()
        if not user32.SetCursorPos(int(event["x"]), int(event["y"])):
            raise RuntimeError("SetCursorPos failed.")
    elif kind == "mouse_down":
        _send_mouse_event(_mouse_flag(event["button"], "down"))
    elif kind == "mouse_up":
        _send_mouse_event(_mouse_flag(event["button"], "up"))
    elif kind == "scroll":
        scroll_x = int(event.get("scroll_x", 0))
        scroll_y = int(event.get("scroll_y", 0))
        if scroll_y:
            _send_mouse_event(MOUSEEVENTF_WHEEL, scroll_y * WHEEL_DELTA)
        if scroll_x:
            _send_mouse_event(MOUSEEVENTF_HWHEEL, scroll_x * WHEEL_DELTA)
    elif kind == "text":
        _send_text(str(event.get("text", "")))
    elif kind == "key":
        _send_key(str(event["key"]))
    elif kind == "hotkey":
        keys = [str(key) for key in event["keys"]]
        for key in keys:
            _send_key_down(key)
        for key in reversed(keys):
            _send_key_up(key)
    else:
        raise ValueError(f"Unsupported input event kind: {kind}")


def _send_text(text: str) -> None:
    for char in text:
        for code_unit in _utf16_code_units(char):
            _send_keyboard_input(0, code_unit, KEYEVENTF_UNICODE)
            _send_keyboard_input(0, code_unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)


def _send_key(key: str) -> None:
    _send_key_down(key)
    _send_key_up(key)


def _send_key_down(key: str) -> None:
    _send_keyboard_input(_virtual_key(key), 0, 0)


def _send_key_up(key: str) -> None:
    _send_keyboard_input(_virtual_key(key), 0, KEYEVENTF_KEYUP)


def _send_mouse_event(flags: int, mouse_data: int = 0) -> None:
    _send_mouse_input(flags, mouse_data)


def _virtual_key(key: str) -> int:
    normalized = str(key).strip().casefold()
    if len(normalized) == 1:
        char = normalized.upper()
        if "A" <= char <= "Z" or "0" <= char <= "9":
            return ord(char)
    if normalized in _VK_KEYS:
        return _VK_KEYS[normalized]
    raise ValueError(f"Unsupported key: {key}")


def _mouse_flag(button: str, direction: str) -> int:
    return _BUTTON_FLAGS[(_button(button), direction)]


def _send_keyboard_input(vk: int, scan: int, flags: int) -> None:
    input_record = INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(
            wVk=int(vk),
            wScan=int(scan),
            dwFlags=int(flags),
            time=0,
            dwExtraInfo=0,
        ),
    )
    _send_input(input_record)


def _send_mouse_input(flags: int, mouse_data: int = 0) -> None:
    input_record = INPUT(
        type=INPUT_MOUSE,
        mi=MOUSEINPUT(
            dx=0,
            dy=0,
            mouseData=ctypes.c_uint32(int(mouse_data)).value,
            dwFlags=int(flags),
            time=0,
            dwExtraInfo=0,
        ),
    )
    _send_input(input_record)


def _send_input(input_record: INPUT) -> None:
    sent = _user32().SendInput(1, ctypes.byref(input_record), ctypes.sizeof(INPUT))
    if sent != 1:
        raise RuntimeError("SendInput failed.")


def _utf16_code_units(char: str) -> list[int]:
    data = char.encode("utf-16-le", "surrogatepass")
    return [data[index] | (data[index + 1] << 8) for index in range(0, len(data), 2)]


def _user32():
    if not hasattr(ctypes, "windll"):
        raise RuntimeError("Native input requires Windows.")
    user32 = ctypes.windll.user32
    _configure_user32(user32)
    return user32


def _configure_user32(user32) -> None:
    user32_id = id(user32)
    if user32_id in _configured_user32_ids:
        return
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    _configured_user32_ids.add(user32_id)
