import asyncio
from types import SimpleNamespace
import pytest

from agent.agents.browser import BrowserAgent
from agent.contracts.browser import BrowserPreferences
from agent.mcp.dedicated_browser import DedicatedBrowser
from agent.contracts.browser import BrowserFrame, BrowserPointer
from test_browser_agent import BrowserTools


def test_requested_routine_click_does_not_stop_for_permission():
    class Tools(BrowserTools):
        def invoke(self, name, payload, *, agent_name):
            result = super().invoke(name, payload, agent_name=agent_name)
            if name.startswith('browser.session'):
                result['preferences'] = {'agent_interactions':'allow'}
            if name == 'browser.routine_action':
                return {'observation':'Observed the clicked page.'}
            return result
    tools = Tools()
    steps = iter([{'action':'click','ref':'@e1'}, {'action':'done','summary':'Opened it.'}])
    result = BrowserAgent(tool_registry=tools, planner=lambda *_: next(steps)).answer('Open this browser link')
    assert result.status == 'answered' and not result.action_request
    assert any(name == 'browser.routine_action' for name, *_ in tools.calls)


def test_agent_reuses_action_observation_instead_of_reading_it_twice():
    tools = BrowserTools()
    steps = iter([{'action':'scroll','direction':'down'}, {'action':'done','summary':'Scrolled.'}])
    assert BrowserAgent(tool_registry=tools, planner=lambda *_: next(steps)).answer('Scroll this browser page').status == 'answered'
    assert sum(name == 'browser_snapshot' for name, *_ in tools.calls) == 1


def test_agent_scroll_can_reach_bottom_in_one_action():
    tools = BrowserTools()
    steps = iter([{'action':'scroll','direction':'bottom'}, {'action':'done','summary':'At bottom.'}])
    result = BrowserAgent(tool_registry=tools, planner=lambda *_: next(steps)).answer('Scroll to the bottom of this browser page')
    assert result.status == 'answered'
    assert next(payload for name,payload,_ in tools.calls if name=='browser_scroll')['direction']=='bottom'


def test_fresh_session_collapses_only_duplicate_blank_startup_tabs(monkeypatch, tmp_path):
    from agent.mcp import dedicated_browser
    monkeypatch.setattr(dedicated_browser, '_resolve_against_repo', lambda path:tmp_path/path)
    monkeypatch.setattr(dedicated_browser, 'browser_readiness', lambda:(True,''))
    import playwright.async_api
    async def check():
        browser = DedicatedBrowser()
        class Page:
            def __init__(self, url): self.url=url; self.closed=False
            def on(self,*_): pass
            def is_closed(self): return self.closed
            async def set_viewport_size(self,*_): pass
            async def close(self): self.closed=True; context.pages.remove(self)
        context = SimpleNamespace(pages=[Page('about:blank'),Page('about:blank')],on=lambda *_:None,
            set_default_timeout=lambda *_:None,set_default_navigation_timeout=lambda *_:None)
        async def launch(_): browser.context=context
        class Start:
            async def start(self): return object()
        monkeypatch.setattr(playwright.async_api,'async_playwright',lambda:Start())
        monkeypatch.setattr(browser,'_open_windows_browser',launch)
        monkeypatch.setattr(browser,'_write_native_preferences',lambda:None)
        await browser.open()
        assert len((await browser.status()).tabs)==1
    asyncio.run(check())


def test_interactions_preference_is_backward_compatible_and_defaults_to_requested_control():
    assert BrowserPreferences().agent_interactions=='allow'


def test_cached_preview_exposes_real_agent_pointer_only_on_current_tab():
    browser=DedicatedBrowser()
    browser.session_id='session'
    browser.active_page=object();browser._pages={'tab':browser.active_page}
    browser.control='agent'
    browser._preview_frame=BrowserFrame(frame_id=browser._frame_id(),tab_id='tab',width=1000,height=700,data_url='pixels')
    browser._pointer=BrowserPointer(tab_id='tab',x=20,y=40,action='click')
    assert browser.cached_frame().pointer==browser._pointer
    browser.control='user'
    assert browser.cached_frame().pointer is None
    browser._revision+=1
    assert browser.cached_frame() is None


@pytest.mark.parametrize('action', ['click', 'type', 'scroll'])
def test_agent_cursor_travels_in_live_frames_before_the_page_action(action):
    """Exercise the locked tool -> read-only frame path used by the live panel."""
    from agent.mcp.playwright_tools import _PlaywrightMcpClient
    async def check():
        browser = DedicatedBrowser()
        browser.control = 'agent'
        browser.session_id = 'cursor-test'
        events, visible_positions = [], []
        client = _PlaywrightMcpClient()
        client._dedicated = browser
        async def move(x, y):
            frame = await asyncio.wait_for(client.session('frame'), .1)
            visible_positions.append((frame.pointer.x, frame.pointer.y))
            events.append('move')
        async def click(*_): events.append('click')
        async def wheel(*_): events.append('scroll')
        class Target:
            async def bounding_box(self): return dict(x=900,y=100,width=60,height=40)
            async def evaluate(self, *_): return True
            async def fill(self, *_): events.append('type')
        page = SimpleNamespace(mouse=SimpleNamespace(move=move,click=click,wheel=wheel),url='about:blank')
        browser.active_page = page
        browser._pages = {'tab':page}
        browser._refs = {'e1':Target()}
        browser._preview_frame = BrowserFrame(frame_id=browser._frame_id(),tab_id='tab',width=1280,height=800,data_url='pixels')
        browser._pointer = BrowserPointer(tab_id='tab',x=120,y=220,action='ready')
        async def snapshot(**_): return 'Observed page.'
        browser.snapshot = snapshot
        async with client._lock_for_current_loop():
            await browser.tool({'action':action,'ref':'@e1','text':'black holes','direction':'down'})
        assert events[-1] == action
        assert len(set(visible_positions)) >= 4, 'The live view must show travel, not one destination'
        assert visible_positions[0] == (120,220)
        destination = (832,440) if action=='scroll' else (930,120)
        assert visible_positions[-1] == pytest.approx(destination)
        assert all(0 <= x < 1280 and 0 <= y < 800 for x,y in visible_positions)
    asyncio.run(check())


def test_navigation_retains_cursor_only_for_the_same_tab():
    browser = DedicatedBrowser()
    browser.active_page = object()
    browser._pages = {'tab':browser.active_page}
    browser._pointer = BrowserPointer(tab_id='tab',x=100,y=200,action='click')
    browser._invalidate()
    assert browser._pointer is not None, 'A page navigation must not make the cursor disappear'
    browser.active_page = object()
    browser._pages['other'] = browser.active_page
    browser._invalidate()
    assert browser._pointer is None


@pytest.mark.parametrize('change', ['take_over', 'navigate'])
def test_cursor_travel_stops_before_typing_when_control_or_page_changes(change):
    from agent.mcp.dedicated_browser import BrowserSessionError
    async def check():
        browser = DedicatedBrowser()
        browser.control = 'agent'
        browser.session_id = 'cursor-test'
        typed = []
        async def move(*_):
            if change == 'take_over': browser.control = 'user'
            else: browser._invalidate()
        class Target:
            async def evaluate(self,*_): return None
            async def bounding_box(self): return dict(x=20,y=30,width=100,height=40)
            async def fill(self,*_): typed.append(True)
        page = SimpleNamespace(mouse=SimpleNamespace(move=move),url='about:blank')
        browser.active_page = page
        browser._pages = {'tab':page}
        browser._refs = {'e1':Target()}
        browser._preview_frame = BrowserFrame(frame_id=browser._frame_id(),tab_id='tab',width=1280,height=800,data_url='pixels')
        with pytest.raises(BrowserSessionError,match='yielded control'):
            await browser.tool({'action':'type','ref':'@e1','text':'must not be typed'})
        assert not typed
    asyncio.run(check())


def test_split_ratio_uses_existing_layout_action_and_rejects_invalid_values():
    from agent.app_actions.runtime import AppActionRuntime
    from agent.app_actions.models import AppActionRequest,AppActionContext
    runtime=AppActionRuntime()
    for value in [20,45,75]:
        assert runtime.dispatch(AppActionRequest(action_id='ui.surface.configure',arguments={'reference':'right-panel','properties':{'chat_ratio':value}}),AppActionContext(source='ui')).status=='applied'
    for value in [19,76,True,'45']:
        assert runtime.dispatch(AppActionRequest(action_id='ui.surface.configure',arguments={'reference':'right-panel','properties':{'chat_ratio':value}}),AppActionContext(source='ui')).status=='failed'


def test_cursor_upload_rejects_remote_urls_scripts_and_bad_images():
    import pytest
    for value in ['https://example.com/cursor.png','data:image/svg+xml;base64,PHN2Zz4=','data:image/png;base64,YQ==']:
        with pytest.raises(ValueError): BrowserPreferences(cursor_style='custom',cursor_image=value)


def test_simple_scroll_uses_the_request_directly_without_waiting_for_model_planning():
    class Tools(BrowserTools):
        def invoke(self,name,payload,*,agent_name):
            result=super().invoke(name,payload,agent_name=agent_name)
            return 'Observed scroll position: 800 of 800 pixels' if name=='browser_scroll' else result
    tools=Tools()
    agent=BrowserAgent(tool_registry=tools,planner=lambda *_: (_ for _ in ()).throw(AssertionError('No model needed')))
    assert agent.answer('Scroll to the bottom of the page').summary=='At the bottom of the page.'
    assert sum(name=='browser_scroll' for name,*_ in tools.calls)==1
    assert not any(name=='browser_snapshot' for name,*_ in tools.calls)


def test_new_chat_browser_request_resumes_manual_control_but_keeps_explicit_pause(monkeypatch):
    from agent.mcp.playwright_tools import _PlaywrightMcpClient
    async def check():
        for previous,expected in [('user','agent'),('paused','paused')]:
            browser=DedicatedBrowser();browser.control=previous;browser.context=object();browser.active_page=object()
            async def opened(): pass
            async def status(): return SimpleNamespace(control=browser.control)
            monkeypatch.setattr(browser,'open',opened);monkeypatch.setattr(browser,'status',status)
            client=_PlaywrightMcpClient();client._dedicated=browser
            assert (await client.session('agent_open')).control==expected
    asyncio.run(check())


@pytest.mark.parametrize('background_only',[False,True])
def test_manual_reopen_starts_on_home_without_clearing_cookies(monkeypatch,background_only):
    from agent.contracts.browser import BrowserControl
    async def check():
        browser=DedicatedBrowser()
        class Page:
            url='https://en.wikipedia.org/wiki/Black_hole'
            closed=False
            async def close(self):self.closed=True;browser._page_closed(self)
            def is_closed(self):return self.closed
        old=Page();fresh=Page();fresh.url='about:blank'
        async def new_page():browser._add_page(fresh);return fresh
        fresh.on=lambda *_:None
        browser.context=object() if background_only else None
        browser.presentation_requested=not background_only
        async def open_():
            browser.context=SimpleNamespace(new_page=new_page)
            browser._pages={'old':old};browser.active_page=old
        async def status():return SimpleNamespace(tabs=list(browser._pages.values()))
        monkeypatch.setattr(browser,'open',open_);monkeypatch.setattr(browser,'status',status)
        result=await browser.ui_control(BrowserControl(operation='open'))
        assert result.tabs==[fresh] and old.closed
    asyncio.run(check())


def test_routine_target_validation_ignores_other_content_but_rejects_changed_control():
    import pytest
    from agent.mcp.dedicated_browser import BrowserSessionError
    async def check():
        browser=DedicatedBrowser()
        descriptor={'role':'button','label':'Search','type':'','href':''}
        class Target:
            async def is_visible(self):return True
            async def is_enabled(self):return True
            async def evaluate(self,_):return descriptor
        browser._refs={'e1':Target()};browser._ref_signatures={'e1':dict(descriptor)}
        browser._snapshot_digest='different whole-page content'
        await browser.verify_routine_target({'action':'click','ref':'@e1'})
        descriptor['label']='Delete account'
        with pytest.raises(BrowserSessionError,match='control changed'):
            await browser.verify_routine_target({'action':'click','ref':'@e1'})
    asyncio.run(check())
