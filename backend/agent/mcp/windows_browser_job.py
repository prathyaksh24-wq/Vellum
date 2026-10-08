"""A Windows lifetime handle for the dedicated browser process only."""
from __future__ import annotations


class WindowsBrowserJob:
    """Close the browser's job when its owning backend exits, including crashes."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                ('flags', wintypes.DWORD), ('minimum_working_set', ctypes.c_size_t),
                ('maximum_working_set', ctypes.c_size_t), ('active_process_limit', wintypes.DWORD),
                ('affinity', ctypes.c_size_t), ('priority_class', wintypes.DWORD),
                ('scheduling_class', wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                'read_operations', 'write_operations', 'other_operations',
                'read_bytes', 'write_bytes', 'other_bytes')]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ('basic', BasicLimits), ('io', IoCounters),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t),
            ]

        self._ctypes = ctypes
        self._pid = None
        kernel = self._kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        # Unnamed, non-inheritable handle: only this backend holds the job alive.
        self._handle = kernel.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, pid: int) -> None:
        # Only the newly launched, application-owned browser is assigned.
        process = self._kernel.OpenProcess(0x00000101, False, pid)  # SET_QUOTA | TERMINATE
        if not process:
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        try:
            if not self._kernel.AssignProcessToJobObject(self._handle, process):
                raise self._ctypes.WinError(self._ctypes.get_last_error())
            self._pid = pid
        finally:
            self._kernel.CloseHandle(process)

    def hide_windows(self) -> None:
        """Keep only this owned browser's native windows behind its preview."""
        if self._pid is None or not self._handle:
            return
        from ctypes import wintypes
        ctypes = self._ctypes
        user = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user.EnumWindows.restype = wintypes.BOOL
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        user.IsWindowVisible.restype = wintypes.BOOL
        @callback_type
        def hide(window, _):
            owner = wintypes.DWORD()
            user.GetWindowThreadProcessId(window, ctypes.byref(owner))
            if owner.value == self._pid and user.IsWindowVisible(window):
                user.ShowWindow(window, 0)  # SW_HIDE; daily Brave is never touched.
            return True
        user.EnumWindows(hide, 0)

    def close(self) -> None:
        handle, self._handle = self._handle, None
        self._pid = None
        if handle:
            self._kernel.CloseHandle(handle)
