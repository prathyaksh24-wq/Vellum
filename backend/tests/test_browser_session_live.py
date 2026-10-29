"""Opt-in real Brave smoke test against disposable pages and downloads only."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest
from agent.mcp import dedicated_browser, playwright_tools

pytestmark = pytest.mark.skipif(os.environ.get('VELLUM_BROWSER_SMOKE') != '1', reason='Set VELLUM_BROWSER_SMOKE=1 for installed Brave')


def visible_owned_windows(pid):
    """Count windows only for the disposable browser, without titles/content."""
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    count = 0
    @callback_type
    def observe(window, _):
        nonlocal count
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == pid and user.IsWindowVisible(window): count += 1
        return True
    user.EnumWindows(observe, 0)
    return count


@pytest.mark.skipif(os.name != 'nt', reason='Windows process lifetime regression')
def test_real_brave_exits_when_backend_process_is_killed(monkeypatch, tmp_path):
    import ctypes
    from ctypes import wintypes

    child_code = '''
import asyncio, sys
from pathlib import Path
from agent.mcp import dedicated_browser
root = Path(sys.argv[1])
dedicated_browser._resolve_against_repo = lambda path: root / path.name
async def main():
    browser = dedicated_browser.DedicatedBrowser()
    await browser.open()
    (root / 'ready.pid').write_text(str(browser._process.pid))
    await asyncio.Future()
asyncio.run(main())
'''
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = None
    monkeypatch.setattr(dedicated_browser, '_resolve_against_repo', lambda path: tmp_path / path.name)
    with (tmp_path / 'child-error.log').open('w') as errors:
        child = subprocess.Popen([sys.executable, '-c', child_code, str(tmp_path)],
            stdout=subprocess.DEVNULL, stderr=errors, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 20
            ready = tmp_path / 'ready.pid'
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.05)
            assert ready.exists(), 'Disposable browser helper did not become ready'
            handle = kernel.OpenProcess(0x00100000, False, int(ready.read_text()))  # SYNCHRONIZE
            assert handle, 'Dedicated browser exited before the backend termination probe'
            child.terminate()
            child.wait(timeout=10)
            assert kernel.WaitForSingleObject(handle, 5000) == 0, 'Backend termination stranded Brave and its profile lock'
            async def reopen():
                browser = dedicated_browser.DedicatedBrowser()
                try:
                    await browser.open()
                    assert (await browser.status()).running, 'Profile could not reopen after backend termination'
                finally:
                    await browser.close()
            asyncio.run(reopen())
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
            if handle:
                if kernel.WaitForSingleObject(handle, 0) != 0:
                    # Clean the disposable orphan even when this regression goes red.
                    async def close_orphan():
                        from playwright.async_api import async_playwright
                        port = int((tmp_path / 'browser-session/profile/DevToolsActivePort').read_text().splitlines()[0])
                        async with async_playwright() as p:
                            browser = await p.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
                            session = await browser.new_browser_cdp_session()
                            try:
                                await session.send('Browser.close')
                            except Exception:
                                pass
                    asyncio.run(close_orphan())
                kernel.CloseHandle(handle)


@pytest.mark.skipif(os.name != 'nt', reason='Owned CDP process transport is Windows-specific')
def test_real_brave_cancelled_disconnect_cleanup_can_reopen(monkeypatch, tmp_path):
    monkeypatch.setattr(dedicated_browser, '_resolve_against_repo', lambda path: tmp_path / path.name)
    async def check():
        browser = dedicated_browser.DedicatedBrowser()
        try:
            await browser.open()
            process = browser._process
            await browser._cdp_browser.close()
            closing = asyncio.create_task(browser.close())
            await asyncio.sleep(.2)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert process.returncode is not None
            await browser.open()
            assert (await browser.status()).running
        finally:
            await browser.close()
    asyncio.run(check())


def test_real_brave_session_tabs_preview_takeover_download_and_shutdown(monkeypatch, tmp_path):
    class Pages(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            if self.path == '/download':
                self.send_header('Content-Disposition', 'attachment; filename="browser-smoke.txt"')
                self.end_headers()
                self.wfile.write(b'disposable browser download')
            else:
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<title>Browser smoke</title><h1>Disposable page</h1><input aria-label="Test field"><a href="/download">Download fixture</a>')
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(('127.0.0.1',0), Pages)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(dedicated_browser, '_resolve_against_repo', lambda path: tmp_path / path.name)
    old_client = playwright_tools._client
    asyncio.run(playwright_tools.shutdown_async())
    monkeypatch.setattr(playwright_tools, '_client', playwright_tools._PlaywrightMcpClient())
    base = f'http://127.0.0.1:{server.server_port}'
    control = lambda **args: playwright_tools.browser_session('control', args)
    try:
        opened = control(operation='open')
        if os.name == 'nt':
            assert visible_owned_windows(playwright_tools._client._dedicated._process.pid) == 0
        assert opened.running and opened.control == 'agent'
        assert (tmp_path/'browser-session/profile').is_dir()
        state = control(operation='navigate', url=base)
        first = state.active_tab_id
        assert state.control == 'user'
        frame = playwright_tools.browser_session('frame')
        assert frame.data_url.startswith('data:image/jpeg;base64,')
        assert (frame.width,frame.height) == (1280,800)
        control(operation='new_tab', url=base + '/second')
        with pytest.raises(ValueError, match='page changed'):
            control(operation='click', x=10, y=10, frame_id=frame.frame_id)
        control(operation='select_tab', tab_id=first)
        control(operation='resume')
        snapshot = playwright_tools.run_tool({'action':'snapshot','full':True})
        assert '@e1' in snapshot and 'Disposable page' in snapshot
        prepared = playwright_tools.browser_session('status').snapshot_id
        # Dynamic page edits must invalidate an already prepared confirmation.
        async def change_link():
            await playwright_tools._client._dedicated.active_page.locator('a').evaluate("el => el.href='/changed'")
        playwright_tools._worker.submit(change_link()).result(timeout=10)
        with pytest.raises(ValueError, match='page content changed'):
            playwright_tools.browser_session('confirmed', {'snapshot_id':prepared, 'params':{'action':'click','ref':'e2'}})
        control(operation='pause')
        assert 'unavailable' in playwright_tools.run_tool({'action':'click','ref':'e1'}).lower()
        assert playwright_tools.browser_session('status').running
        control(operation='take_over')
        fresh = playwright_tools.browser_session('frame')
        control(operation='click', x=35, y=90, frame_id=fresh.frame_id)
        control(operation='resume')
        result = playwright_tools.run_tool({'action':'navigate','url':base + '/download'})
        assert 'unavailable' not in result.lower()
        deadline = time.monotonic()+10
        while time.monotonic()<deadline:
            downloads = playwright_tools.browser_session('status').downloads
            if downloads and downloads[-1].state == 'saved': break
            time.sleep(.1)
        assert downloads[-1].state == 'saved'
        saved = tmp_path/'browser-downloads'/downloads[-1].id/downloads[-1].name
        assert saved.read_bytes() == b'disposable browser download'
        state = control(operation='close')
        assert not state.running and not state.tabs
        assert saved.exists()
        state = control(operation='open')
        assert state.running and state.tabs
        for tab in list(state.tabs):
            control(operation='close_tab', tab_id=tab.id)
        state = control(operation='navigate', url=base)
        assert state.tabs and state.active_tab_id
        assert playwright_tools.browser_session('frame').tab_id == state.active_tab_id
        control(operation='navigate', url=base + '/download')
        deadline = time.monotonic()+10
        while time.monotonic()<deadline:
            second = playwright_tools.browser_session('status').downloads[-1]
            if second.id != downloads[-1].id and second.state == 'saved': break
            time.sleep(.1)
        assert second.id != downloads[-1].id and second.state == 'saved'
    finally:
        asyncio.run(playwright_tools.shutdown_async())
        monkeypatch.setattr(playwright_tools, '_client', old_client)
        server.shutdown()
        server.server_close()
