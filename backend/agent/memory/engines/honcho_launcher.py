"""Launch Honcho on Windows without editing its source.

Run by Honcho's own Python (3.13), with Honcho's source folder as cwd:

    python honcho_launcher.py api <port>
    python honcho_launcher.py deriver
    python honcho_launcher.py script <path> [args...]

This file must not import anything from Vellum: it runs in Honcho's
environment. The fixes, each found by running Honcho natively on Windows:

1. psycopg's async driver refuses the default Proactor event loop, so use
   the selector loop (uvicorn needs ``loop="asyncio:SelectorEventLoop"``).
2. The deriver imports uvloop, which has no Windows build: alias it.
3. A telemetry module imports fcntl (POSIX-only) just to lock a trace
   file: give it a no-op stub.
4. ``loop.add_signal_handler`` is unsupported on Windows: fall back to
   ``signal.signal`` plus ``call_soon_threadsafe``.

On other platforms the fixes are skipped and Honcho runs unchanged.
"""
from __future__ import annotations

import asyncio
import runpy
import signal
import sys
import types


def _apply_windows_fixes() -> None:
    policy = asyncio.WindowsSelectorEventLoopPolicy  # type: ignore[attr-defined]
    asyncio.set_event_loop_policy(policy())
    sys.modules.setdefault("uvloop", types.SimpleNamespace(EventLoopPolicy=policy))  # type: ignore[arg-type]
    sys.modules.setdefault("fcntl", types.SimpleNamespace(flock=lambda *a: None, LOCK_EX=2, LOCK_UN=8))  # type: ignore[arg-type]

    def add_signal_handler(self, sig, callback, *args):  # noqa: ANN001
        def handler(signum, frame):  # noqa: ANN001, ARG001
            self.call_soon_threadsafe(callback, *args)

        signal.signal(sig, handler)

    asyncio.SelectorEventLoop.add_signal_handler = add_signal_handler  # type: ignore[method-assign]


def main(argv: list[str]) -> None:
    windows = sys.platform == "win32"
    if windows:
        _apply_windows_fixes()
    sys.path.insert(0, ".")
    mode = argv[0]
    if mode == "api":
        import uvicorn

        uvicorn.run("src.main:app", host="127.0.0.1", port=int(argv[1]),
                    loop="asyncio:SelectorEventLoop" if windows else "auto", log_level="warning")
    elif mode == "deriver":
        sys.argv = ["src.deriver"]
        runpy.run_module("src.deriver", run_name="__main__", alter_sys=True)
    elif mode == "script":
        sys.argv = argv[1:]
        runpy.run_path(argv[1], run_name="__main__")
    else:
        raise SystemExit(f"unknown mode {mode!r}: use api <port> | deriver | script <path> [args]")


if __name__ == "__main__":
    main(sys.argv[1:])
