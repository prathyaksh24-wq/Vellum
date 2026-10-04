"""Opt-in real Brave smoke test against disposable pages and downloads only."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
import time

import pytest
from agent.mcp import dedicated_browser, playwright_tools

pytestmark = pytest.mark.skipif(os.environ.get('VELLUM_BROWSER_SMOKE') != '1', reason='Set VELLUM_BROWSER_SMOKE=1 for installed Brave')


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
