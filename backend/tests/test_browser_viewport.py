import asyncio
import os
from types import SimpleNamespace

import pytest

from agent.contracts.browser import BrowserControl
from agent.mcp.dedicated_browser import BrowserSessionError, DedicatedBrowser


@pytest.mark.skipif(os.name != 'nt', reason='Windows launch transport')
@pytest.mark.parametrize('endpoint_kind', ['owned', 'other_port', 'remote_host'])
def test_windows_launch_uses_owned_normal_browser_endpoint(monkeypatch, tmp_path, endpoint_kind):
    from agent.mcp import dedicated_browser, windows_browser_job
    captured, connections, jobs = {}, [], []
    class Job:
        def __init__(self): pass
        def assign(self, pid): jobs.append(pid)
        def hide_windows(self): jobs.append('hidden')
    async def spawn(*args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        port = next(arg.split('=', 1)[1] for arg in args if arg.startswith('--remote-debugging-port='))
        endpoint_port = str(int(port) + 1) if endpoint_kind == 'other_port' else port
        host = 'example.com' if endpoint_kind == 'remote_host' else '127.0.0.1'
        reader = asyncio.StreamReader()
        reader.feed_data(f'DevTools listening on ws://{host}:{endpoint_port}/devtools/browser/12345678-abcd-1234-abcd-123456789abc\n'.encode())
        reader.feed_eof()
        return SimpleNamespace(pid=123, returncode=None, stderr=reader)
    context = object()
    async def connect(endpoint, **_):
        connections.append(endpoint)
        return SimpleNamespace(contexts=[context])
    monkeypatch.setattr(windows_browser_job, 'WindowsBrowserJob', Job)
    monkeypatch.setattr(dedicated_browser.asyncio, 'create_subprocess_exec', spawn)
    async def check():
        browser = DedicatedBrowser()
        browser.playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect))
        # A stale discovery file must never select another browser's endpoint.
        (tmp_path / 'profile').mkdir()
        (tmp_path / 'profile/DevToolsActivePort').write_text('9222\n/devtools/browser/stale\n')
        if endpoint_kind != 'owned':
            with pytest.raises(BrowserSessionError, match='did not become ready'):
                await browser._open_windows_browser(tmp_path)
            assert not connections
            assert not (tmp_path / 'profile/DevToolsActivePort').exists()
            return
        await browser._open_windows_browser(tmp_path)
        assert browser.context is context
        assert '--headless=new' not in captured['args']
        assert '--window-position=-32000,-32000' in captured['args']
        assert '--remote-debugging-address=127.0.0.1' in captured['args']
        assert jobs == [123, 'hidden']
        assert connections[0].endswith('/devtools/browser/12345678-abcd-1234-abcd-123456789abc')
        port = int((tmp_path / 'profile/DevToolsActivePort').read_text().splitlines()[0])
        assert 0 < port < 65536
        assert connections[0].startswith(f'ws://127.0.0.1:{port}/')
        if browser._stderr_task: await browser._stderr_task
    asyncio.run(check())


@pytest.mark.parametrize('operation,url,expected', [
    ('open', '', 'about:blank'),
    ('new_tab', '', 'about:blank'),
    ('new_tab', 'https://www.youtube.com/', 'https://www.youtube.com/'),
    ('new_tab', 'about:blank', 'about:blank'),
])
def test_user_open_and_new_tab_show_homepage(monkeypatch, operation, url, expected):
    async def check():
        browser = DedicatedBrowser()
        page = SimpleNamespace(url='about:blank')
        async def new_page():
            browser.active_page = page
            return page
        async def opened(): pass
        async def goto(target, destination): target.url = destination
        async def status(): return SimpleNamespace(url=browser.active_page.url)
        browser.context = SimpleNamespace(new_page=new_page)
        browser.active_page = page
        monkeypatch.setattr(browser, 'open', opened)
        monkeypatch.setattr(browser, '_goto', goto)
        monkeypatch.setattr(browser, 'status', status)
        state = await browser.ui_control(BrowserControl(operation=operation, url=url))
        if browser._tasks: await asyncio.gather(*list(browser._tasks))
        assert (await browser.status()).url == expected
    asyncio.run(check())


@pytest.mark.parametrize('caller', ['ui', 'agent'])
def test_closing_last_tab_keeps_native_session_alive(monkeypatch, caller):
    async def check():
        browser = DedicatedBrowser()
        page, blank = SimpleNamespace(), SimpleNamespace(url='about:blank')
        browser.control = 'agent'
        browser._pages = {'old':page}
        browser.active_page = page
        async def new_page():
            browser._pages['replacement'] = blank
            browser.active_page = blank
            return blank
        async def close():
            assert 'replacement' in browser._pages, 'Native Brave exits if its last page closes first'
            browser._page_closed(page)
        async def status(): return SimpleNamespace(tabs=[])
        page.close = close
        browser.context = SimpleNamespace(new_page=new_page)
        monkeypatch.setattr(browser, 'status', status)
        if caller == 'ui': await browser.ui_control(BrowserControl(operation='close_tab', tab_id='old'))
        else: await browser.tool({'action':'tabs', 'tab_action':'close', 'index':0})
        assert browser.active_page is blank and list(browser._pages) == ['replacement']
    asyncio.run(check())


def test_open_keeps_existing_website(monkeypatch):
    async def check():
        browser = DedicatedBrowser()
        browser.active_page = SimpleNamespace(url='https://www.youtube.com/')
        async def opened(): pass
        async def status(): return SimpleNamespace(url=browser.active_page.url)
        monkeypatch.setattr(browser, 'open', opened)
        monkeypatch.setattr(browser, 'status', status)
        state = await browser.ui_control(BrowserControl(operation='open'))
        assert state.url == 'https://www.youtube.com/'
    asyncio.run(check())


def test_new_tabs_do_not_wait_for_slow_homepage(monkeypatch):
    async def check():
        browser = DedicatedBrowser()
        gate = asyncio.Event()
        pages = []
        class Page:
            url = 'about:blank'
            def is_closed(self): return False
            async def title(self):
                await gate.wait()
                return 'Loaded page'
        async def new_page():
            page = Page()
            pages.append(page); browser.active_page = page
            browser._pages[str(len(pages))] = page
            return page
        async def goto(page, destination):
            await gate.wait(); page.url = destination
        browser.context = SimpleNamespace(new_page=new_page)
        monkeypatch.setattr(browser,'_goto',goto)
        try:
            for _ in range(3):
                result = await asyncio.wait_for(browser.ui_control(BrowserControl(operation='new_tab')), .2)
            assert len(result.tabs) == 3 and all(not tab.loading and tab.url == 'about:blank' for tab in result.tabs)
            assert not browser._tasks
        finally:
            gate.set()
            if browser._tasks: await asyncio.gather(*list(browser._tasks))
    asyncio.run(check())


def test_resize_preserves_agent_ownership_and_rejects_stale_clicks(monkeypatch):
    async def check():
        browser = DedicatedBrowser()
        page = SimpleNamespace(viewport_size={'width':1280,'height':800}, is_closed=lambda:False)
        sizes, clicks = [], []
        async def set_size(size):
            sizes.append(size); page.viewport_size = size
        async def screenshot(**_): return b'fixture'
        async def click(x,y): clicks.append((x,y))
        async def status(): return SimpleNamespace(control=browser.control)
        page.set_viewport_size = set_size
        page.screenshot = screenshot
        page.mouse = SimpleNamespace(click=click)
        browser.context = object()
        class Preview:
            def on(self, _event, callback): self.receive = callback
            async def send(self, *_): pass
            async def detach(self): pass
        preview = Preview()
        async def new_session(_): return preview
        browser.context = SimpleNamespace(new_cdp_session=new_session)
        browser.active_page = page
        browser._pages = {'tab':page}
        browser.session_id = 'session'
        browser.control = 'agent'
        monkeypatch.setattr(browser,'status',status)
        before = await browser.frame()
        browser.snapshot_id = 'prepared-agent-action'
        await browser.ui_control(BrowserControl(operation='take_over',frame_id=before.frame_id))
        assert browser.snapshot_id == '' and (await browser.frame()).frame_id == before.frame_id
        browser.control = 'agent'
        await browser.ui_control(BrowserControl(operation='resize',tab_id='tab',width=920,height=710))
        assert browser.control == 'agent'
        with pytest.raises(BrowserSessionError,match='page changed'):
            await browser.ui_control(BrowserControl(operation='take_over',frame_id=before.frame_id))
        assert browser.control == 'agent'
        fresh = await browser.frame()
        assert (fresh.width,fresh.height) == (920,710)
        assert sizes == [{'width':920,'height':710}]
        browser.snapshot_id = 'agent-confirmation'
        with pytest.raises(BrowserSessionError,match='outside'):
            await browser.ui_control(BrowserControl(operation='click',x=925,y=20,frame_id=fresh.frame_id,take_control=True))
        assert browser.control == 'agent' and browser.snapshot_id == 'agent-confirmation'
        await browser.ui_control(BrowserControl(operation='click',x=40,y=20,frame_id=fresh.frame_id,take_control=True))
        assert browser.control == 'user' and browser.snapshot_id == ''
        browser.control = 'user'
        with pytest.raises(BrowserSessionError,match='page changed'):
            await browser.ui_control(BrowserControl(operation='click',x=20,y=20,frame_id=before.frame_id))
        with pytest.raises(BrowserSessionError,match='outside'):
            await browser.ui_control(BrowserControl(operation='click',x=925,y=20,frame_id=fresh.frame_id))
        await browser.ui_control(BrowserControl(operation='click',x=900,y=700,frame_id=fresh.frame_id))
        assert clicks == [(40,20),(900,700)]
        with pytest.raises(BrowserSessionError,match='active tab changed'):
            await browser.ui_control(BrowserControl(operation='resize',tab_id='old',width=900,height=700))
    asyncio.run(check())


def test_live_frame_cache_drops_old_document_frames(monkeypatch):
    async def check():
        browser = DedicatedBrowser()
        captures, sessions = [], []
        class Preview:
            def on(self, _event, callback): self.receive = callback
            async def send(self, *_): pass
            async def detach(self): pass
        async def new_session(_):
            session = Preview(); sessions.append(session); return session
        async def capture(**_): captures.append(True); return b'initial'
        page = SimpleNamespace(viewport_size=browser._viewport, is_closed=lambda:False, screenshot=capture)
        browser.context = SimpleNamespace(new_cdp_session=new_session)
        browser.active_page = page
        browser._pages = {'tab':page}
        browser.session_id = 'session'
        initial = await browser.frame()
        old_session = sessions[0]
        old_session.receive({'sessionId':1,'data':'changed'})
        assert (await browser.frame()).data_url.endswith('changed')
        assert captures == [True], 'Frame readers captured another screenshot instead of using the live feed'
        browser._invalidate()
        old_session.receive({'sessionId':2,'data':'stale'})
        fresh = await browser.frame()
        assert fresh.frame_id != initial.frame_id and not fresh.data_url.endswith('stale')
        old_session.receive({'sessionId':3,'data':'stale'})
        assert (await browser.frame()) == fresh
        await browser._stop_preview()
        await asyncio.gather(*list(browser._tasks))
    asyncio.run(check())


def test_loading_tab_frame_never_enters_blocking_browser_awaits():
    async def check():
        browser = DedicatedBrowser()
        page = SimpleNamespace(is_closed=lambda:False)
        browser.active_page = page
        browser._tab_loads[id(page)] = object()
        with pytest.raises(BrowserSessionError, match='loading'):
            await asyncio.wait_for(browser.frame(), .1)
    asyncio.run(check())


def test_background_and_child_navigation_keep_active_preview_identity():
    browser = DedicatedBrowser()
    page = SimpleNamespace(main_frame=object())
    background = SimpleNamespace(main_frame=object())
    browser.active_page = page
    browser._pages = {'active':page,'background':background}
    browser.session_id = 'session'
    identity = browser._frame_id()
    browser.snapshot_id = 'agent-confirmation'
    browser._frame_navigated(background, background.main_frame)
    assert browser._frame_id() == identity and browser.snapshot_id == 'agent-confirmation'
    browser._frame_navigated(page, object())
    assert browser._frame_id() == identity and browser.snapshot_id == ''
    browser._page_closed(background)
    assert browser._frame_id() == identity
    browser._frame_navigated(page, page.main_frame)
    assert browser._frame_id() != identity


def test_explicit_navigation_cancels_pending_homepage():
    async def check():
        browser = DedicatedBrowser()
        started = asyncio.Event()
        cancelled = []
        class Page:
            url = 'about:blank'
            async def goto(self, url, **_):
                if url == 'https://www.google.com/':
                    started.set()
                    try: await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        cancelled.append(True)
                        raise
                self.url = url
        page = Page()
        browser._start_tab_load(page, 'https://www.google.com/')
        await started.wait()
        await browser._goto(page, 'https://www.youtube.com/')
        assert cancelled == [True] and page.url == 'https://www.youtube.com/'
        assert not browser._tab_loads
    asyncio.run(check())


@pytest.mark.parametrize('origin,expected', [
    ('http://127.0.0.1:5173',True),('http://localhost:5180',True),
    ('https://evil.example',False),('http://localhost.evil.example',False),
    ('http://localhost:5173@evil.example',False),(None,False),('null',False),
])
def test_browser_stream_origin(origin, expected):
    from agent.mcp.browser_api import local_preview_origin
    assert local_preview_origin(origin) is expected


def test_stream_rejects_remote_origins_and_never_dispatches_input(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from agent.contracts.browser import BrowserFrame
    from agent.mcp import browser_api
    calls = []
    def frame(operation, *_):
        calls.append(operation)
        return BrowserFrame(frame_id='session:tab:1',tab_id='tab',width=900,height=700,
            data_url='data:image/jpeg;base64,Zml4dHVyZQ==')
    monkeypatch.setattr(browser_api,'browser_session',frame)
    app = FastAPI()
    app.include_router(browser_api.router,prefix='/api')
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect('/api/browser/stream',headers={'origin':'https://evil.example'}):
                pass
        assert rejected.value.code == 1008 and calls == []
        with client.websocket_connect('/api/browser/stream',headers={'origin':'http://localhost:5173'}) as socket:
            assert socket.receive_json()['tab_id'] == 'tab'
            socket.send_text('{"operation":"type","text":"ignored"}')
        assert calls and set(calls) == {'frame'}
