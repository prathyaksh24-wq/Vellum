from __future__ import annotations

import ctypes

from agent.computer_use import input_guard


def test_low_level_hook_proc_uses_pointer_sized_lresult():
    proc_type = input_guard.WindowsInputGuard._low_level_proc_type()

    assert proc_type is input_guard.LOW_LEVEL_PROC
    assert proc_type._restype_ is input_guard.LRESULT
    assert proc_type._argtypes_[0] is ctypes.c_int
    assert proc_type._argtypes_[1] is input_guard.WPARAM
    assert proc_type._argtypes_[2] is input_guard.LPARAM


def test_configure_hook_api_sets_full_pointer_safe_signatures():
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
    assert fake.SetWindowsHookExW.restype is input_guard.HHOOK
    assert fake.SetWindowsHookExW.argtypes == [
        ctypes.c_int,
        input_guard.LOW_LEVEL_PROC,
        input_guard.wintypes.HINSTANCE,
        input_guard.wintypes.DWORD,
    ]
    assert fake.UnhookWindowsHookEx.argtypes == [input_guard.HHOOK]
    assert fake.UnhookWindowsHookEx.restype is input_guard.wintypes.BOOL


def test_call_next_hook_casts_large_lparam_as_pointer_sized_value():
    calls = []

    class FakeUser32:
        def CallNextHookEx(self, hook, n_code, w_param, l_param):
            calls.append((hook, n_code, w_param, l_param))
            return 123

    large_lparam = 0x7FFFFFFFFFFF

    result = input_guard.WindowsInputGuard._call_next_hook(
        FakeUser32(),
        input_guard.HHOOK(77),
        -1,
        input_guard.WPARAM(256),
        large_lparam,
    )

    assert result == 123
    _, n_code, _, l_param = calls[0]
    assert isinstance(n_code, ctypes.c_int)
    assert isinstance(l_param, input_guard.LPARAM)
    assert l_param.value == large_lparam
