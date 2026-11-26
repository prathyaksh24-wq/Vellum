"""Run automation work on the server's own event loop.

The agent runtime caches loop-bound objects (build locks, the async checkpointer,
HTTP clients). Running an automation through ``asyncio.run`` in a worker thread
builds those objects on a throwaway loop; the next run on the server loop then
fails with "... is bound to a different event loop". Every run therefore goes
through the loop the API server (and the scheduler) uses.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Awaitable, Callable

_SERVER_LOOP: asyncio.AbstractEventLoop | None = None


def set_server_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    global _SERVER_LOOP
    _SERVER_LOOP = loop


def server_loop() -> asyncio.AbstractEventLoop | None:
    loop = _SERVER_LOOP
    if loop is None or loop.is_closed() or not loop.is_running():
        return None
    return loop


def _on_loop_thread(loop: asyncio.AbstractEventLoop) -> bool:
    try:
        return asyncio.get_running_loop() is loop
    except RuntimeError:
        return False


def submit(factory: Callable[[], Awaitable[Any]]) -> Future | asyncio.Task | None:
    """Start the coroutine on the server loop without waiting; None when no server loop runs."""
    loop = server_loop()
    if loop is None:
        return None
    if _on_loop_thread(loop):
        return loop.create_task(factory())
    return asyncio.run_coroutine_threadsafe(factory(), loop)


def run_and_wait(factory: Callable[[], Awaitable[Any]], timeout: float | None = None) -> Any:
    """Run the coroutine on the server loop and wait for its result from a worker thread.

    Without a running server loop (tests, CLI) the coroutine runs in a private loop,
    which is safe there because nothing else shares the agent runtime.
    """
    loop = server_loop()
    if loop is None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(factory())
        result: dict[str, Any] = {}

        def worker() -> None:
            try:
                result["value"] = asyncio.run(factory())
            except BaseException as exc:  # noqa: BLE001 — re-raised in the caller
                result["error"] = exc

        thread = threading.Thread(target=worker, name="vellum-automation-run", daemon=True)
        thread.start()
        thread.join(timeout)
        if "error" in result:
            raise result["error"]
        return result.get("value")
    if _on_loop_thread(loop):
        raise RuntimeError("run_and_wait cannot block the server loop; use submit() instead")
    return asyncio.run_coroutine_threadsafe(factory(), loop).result(timeout)
