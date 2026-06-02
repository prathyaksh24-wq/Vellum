from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterable

from agent.computer_use.operator import ComputerWindow


@dataclass(frozen=True)
class ResolvedApp:
    executable: str
    match_terms: tuple[str, ...]


BRAVE_COMMON_CANDIDATES = (
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
)


def resolve_app(
    app: str,
    *,
    exists: Callable[[str], bool] | None = None,
) -> ResolvedApp:
    clean = app.strip()
    exists = exists or (lambda candidate: Path(candidate).exists())

    if _is_explicit_exe_path(clean):
        if not exists(clean):
            raise FileNotFoundError(f"Executable does not exist: {clean}")
        filename = _exe_name(clean)
        return ResolvedApp(clean, (_exe_stem(filename), filename.lower()))

    normalized = clean.casefold()
    if normalized in {"notepad", "notepad.exe"}:
        return ResolvedApp("notepad.exe", ("notepad", "notepad.exe"))

    if normalized in {"brave", "brave.exe", "brave browser"}:
        candidates = (*BRAVE_COMMON_CANDIDATES, _local_brave_candidate(), "brave.exe")
        executable = next((candidate for candidate in candidates if exists(candidate)), candidates[-1])
        return ResolvedApp(executable, ("brave", "brave.exe"))

    raise ValueError(f"Unknown app alias: {app}")


def launch_app(
    app: str,
    *,
    list_windows: Callable[[], list[ComputerWindow]],
) -> ComputerWindow:
    resolved = resolve_app(app)
    subprocess.Popen(
        [resolved.executable],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return wait_for_launched_window(resolved.match_terms, list_windows=list_windows)


def wait_for_launched_window(
    match_terms: Iterable[str],
    *,
    list_windows: Callable[[], list[ComputerWindow]],
    timeout: float = 10.0,
    poll_interval: float = 0.25,
) -> ComputerWindow:
    terms = tuple(term.casefold() for term in match_terms)
    deadline = time.monotonic() + timeout

    while True:
        for window in list_windows():
            haystack = f"{window.app} {window.title}".casefold()
            if any(term in haystack for term in terms):
                return window

        if time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for launched app window.")
        time.sleep(poll_interval)


def _is_explicit_exe_path(value: str) -> bool:
    windows_path = PureWindowsPath(value)
    return (
        windows_path.suffix.casefold() == ".exe"
        and (
            "\\" in value
            or "/" in value
            or bool(windows_path.drive)
            or bool(windows_path.root)
        )
    )


def _exe_name(value: str) -> str:
    if "\\" in value or PureWindowsPath(value).drive:
        return PureWindowsPath(value).name
    return Path(value).name


def _exe_stem(filename: str) -> str:
    return PureWindowsPath(filename).stem.casefold()


def _local_brave_candidate() -> str:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        base = Path(local_appdata)
    else:
        base = Path.home() / "AppData" / "Local"
    return str(base / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe")
