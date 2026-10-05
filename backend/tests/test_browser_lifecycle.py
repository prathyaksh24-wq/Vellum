import asyncio
from types import SimpleNamespace

import pytest

from agent.mcp import dedicated_browser


class OwnedProcess:
    def __init__(self):
        self.returncode = None
        self.waiting = asyncio.Event()
        self.exited = asyncio.Event()

    async def wait(self):
        self.waiting.set()
        await self.exited.wait()
        return self.returncode

    def terminate(self):
        self.returncode = -15
        self.exited.set()


class DisconnectedBrowser:
    async def new_browser_cdp_session(self):
        raise RuntimeError('Transport disconnected')


def test_cancelled_close_finishes_owned_process_cleanup(monkeypatch):
    original_wait_for = asyncio.wait_for
    async def bounded_wait(awaitable, timeout):
        return await original_wait_for(awaitable, min(timeout, .05))
    monkeypatch.setattr(dedicated_browser.asyncio, 'wait_for', bounded_wait)

    async def check():
        browser = dedicated_browser.DedicatedBrowser()
        process = OwnedProcess()
        stopped = []
        async def stop():
            stopped.append(True)
        browser._process = process
        browser._cdp_browser = DisconnectedBrowser()
        browser.playwright = SimpleNamespace(stop=stop)
        closing = asyncio.create_task(browser.close())
        await process.waiting.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert process.returncode is not None, 'Cancelled cleanup left the owned browser alive'
        assert stopped == [True]
    asyncio.run(check())


def test_concurrent_close_waits_for_existing_cleanup():
    async def check():
        browser = dedicated_browser.DedicatedBrowser()
        process = OwnedProcess()
        browser._process = process
        first = asyncio.create_task(browser.close())
        await process.waiting.wait()
        second = asyncio.create_task(browser.close())
        await asyncio.sleep(0)
        try:
            assert not second.done(), 'A second close returned while the browser was still alive'
        finally:
            process.terminate()
            await asyncio.gather(first, second)
    asyncio.run(check())
