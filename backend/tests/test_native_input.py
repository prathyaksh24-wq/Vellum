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
