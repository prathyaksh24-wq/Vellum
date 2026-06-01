import ctypes

import pytest

from agent.computer_use.native_windows import input as native_input


class FakeUser32:
    def __init__(self, *, send_results=None, set_cursor_result=1):
        self.cursor_positions = []
        self.inputs = []
        self.send_results = list(send_results or [])
        self.set_cursor_result = set_cursor_result

    def SendInput(self, count, pointer, size):
        record = ctypes.cast(pointer, ctypes.POINTER(native_input.INPUT)).contents
        if record.type == native_input.INPUT_KEYBOARD:
            self.inputs.append(
                {
                    "type": "keyboard",
                    "vk": int(record.ki.wVk),
                    "scan": int(record.ki.wScan),
                    "flags": int(record.ki.dwFlags),
                    "count": int(count),
                    "size": int(size),
                }
            )
        elif record.type == native_input.INPUT_MOUSE:
            self.inputs.append(
                {
                    "type": "mouse",
                    "flags": int(record.mi.dwFlags),
                    "data": int(record.mi.mouseData),
                    "count": int(count),
                    "size": int(size),
                }
            )
        if self.send_results:
            return self.send_results.pop(0)
        return 1

    def SetCursorPos(self, x, y):
        self.cursor_positions.append((int(x), int(y)))
        return self.set_cursor_result


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


def test_click_rejects_non_positive_click_count():
    with pytest.raises(ValueError, match="click_count"):
        native_input.click(10, 20, click_count=0, sender=lambda event: None)


def test_type_text_requires_string():
    with pytest.raises(TypeError, match="string"):
        native_input.type_text(None, sender=lambda event: None)


def test_native_key_dispatch_sends_key_down_and_up(monkeypatch):
    user32 = FakeUser32()
    monkeypatch.setattr(native_input, "_user32", lambda: user32)

    native_input._send_event({"kind": "key", "key": "a"})

    assert user32.inputs == [
        {
            "type": "keyboard",
            "vk": ord("A"),
            "scan": 0,
            "flags": 0,
            "count": 1,
            "size": ctypes.sizeof(native_input.INPUT),
        },
        {
            "type": "keyboard",
            "vk": ord("A"),
            "scan": 0,
            "flags": native_input.KEYEVENTF_KEYUP,
            "count": 1,
            "size": ctypes.sizeof(native_input.INPUT),
        },
    ]


def test_failed_send_input_includes_last_error(monkeypatch):
    user32 = FakeUser32(send_results=[0])
    monkeypatch.setattr(native_input, "_user32", lambda: user32)
    monkeypatch.setattr(native_input.ctypes, "get_last_error", lambda: 5, raising=False)

    with pytest.raises(RuntimeError, match=r"SendInput failed .*last_error=5"):
        native_input._send_event({"kind": "key", "key": "a"})


def test_failed_set_cursor_pos_includes_last_error(monkeypatch):
    user32 = FakeUser32(set_cursor_result=0)
    monkeypatch.setattr(native_input, "_user32", lambda: user32)
    monkeypatch.setattr(native_input.ctypes, "get_last_error", lambda: 87, raising=False)

    with pytest.raises(RuntimeError, match=r"SetCursorPos failed .*last_error=87"):
        native_input._send_event({"kind": "move", "x": 10, "y": 20})


def test_native_scroll_sends_wheel_data(monkeypatch):
    user32 = FakeUser32()
    monkeypatch.setattr(native_input, "_user32", lambda: user32)

    native_input._send_event({"kind": "scroll", "scroll_x": 3, "scroll_y": 2})

    assert user32.inputs == [
        {
            "type": "mouse",
            "flags": native_input.MOUSEEVENTF_WHEEL,
            "data": 2 * native_input.WHEEL_DELTA,
            "count": 1,
            "size": ctypes.sizeof(native_input.INPUT),
        },
        {
            "type": "mouse",
            "flags": native_input.MOUSEEVENTF_HWHEEL,
            "data": 3 * native_input.WHEEL_DELTA,
            "count": 1,
            "size": ctypes.sizeof(native_input.INPUT),
        },
    ]


def test_native_mouse_buttons_send_expected_flags(monkeypatch):
    user32 = FakeUser32()
    monkeypatch.setattr(native_input, "_user32", lambda: user32)

    native_input._send_event({"kind": "mouse_down", "button": "right"})
    native_input._send_event({"kind": "mouse_up", "button": "right"})
    native_input._send_event({"kind": "mouse_down", "button": "middle"})
    native_input._send_event({"kind": "mouse_up", "button": "middle"})

    assert [event["flags"] for event in user32.inputs] == [
        native_input.MOUSEEVENTF_RIGHTDOWN,
        native_input.MOUSEEVENTF_RIGHTUP,
        native_input.MOUSEEVENTF_MIDDLEDOWN,
        native_input.MOUSEEVENTF_MIDDLEUP,
    ]


def test_native_text_sends_unicode_down_and_up(monkeypatch):
    user32 = FakeUser32()
    monkeypatch.setattr(native_input, "_user32", lambda: user32)

    native_input._send_event({"kind": "text", "text": "é"})

    assert user32.inputs == [
        {
            "type": "keyboard",
            "vk": 0,
            "scan": ord("é"),
            "flags": native_input.KEYEVENTF_UNICODE,
            "count": 1,
            "size": ctypes.sizeof(native_input.INPUT),
        },
        {
            "type": "keyboard",
            "vk": 0,
            "scan": ord("é"),
            "flags": native_input.KEYEVENTF_UNICODE | native_input.KEYEVENTF_KEYUP,
            "count": 1,
            "size": ctypes.sizeof(native_input.INPUT),
        },
    ]


def test_hotkey_validates_all_keys_before_pressing(monkeypatch):
    user32 = FakeUser32()
    monkeypatch.setattr(native_input, "_user32", lambda: user32)

    with pytest.raises(ValueError, match="Unsupported key"):
        native_input._send_event({"kind": "hotkey", "keys": ["ctrl", "not-a-key"]})

    assert user32.inputs == []


def test_hotkey_releases_pressed_keys_when_later_key_down_fails(monkeypatch):
    user32 = FakeUser32(send_results=[1, 0, 1])
    monkeypatch.setattr(native_input, "_user32", lambda: user32)

    with pytest.raises(RuntimeError, match="SendInput failed"):
        native_input._send_event({"kind": "hotkey", "keys": ["ctrl", "shift"]})

    assert [
        (event["vk"], event["flags"])
        for event in user32.inputs
        if event["type"] == "keyboard"
    ] == [
        (native_input._virtual_key("ctrl"), 0),
        (native_input._virtual_key("shift"), 0),
        (native_input._virtual_key("ctrl"), native_input.KEYEVENTF_KEYUP),
    ]


def test_drag_releases_mouse_button_when_target_move_fails():
    calls = []

    def sender(event):
        calls.append(event)
        if event == {"kind": "move", "x": 30, "y": 40}:
            raise RuntimeError("move failed")

    with pytest.raises(RuntimeError, match="move failed"):
        native_input.drag(10, 20, 30, 40, sender=sender)

    assert calls == [
        {"kind": "move", "x": 10, "y": 20},
        {"kind": "mouse_down", "button": "left"},
        {"kind": "move", "x": 30, "y": 40},
        {"kind": "mouse_up", "button": "left"},
    ]
