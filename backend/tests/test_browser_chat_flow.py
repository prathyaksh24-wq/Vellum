"""Regressions from the saved Wikipedia/YouTube conversation."""
import pytest
from agent.agents.browser import BrowserAgent
from agent.tools.registry import ToolRegistry


@pytest.mark.parametrize('message', ['which search engine am i using?', 'what is my current search engine?', 'change the search engine to DuckDuckGo', 'use Brave as my search engine'])
def test_engine_requests_use_saved_preferences_without_opening_or_planning(message):
    class Tools:
        def __init__(self): self.calls=[]
        def invoke(self,name,payload,*,agent_name):
            self.calls.append((name,payload))
            return {'preferences':{'search_engine':payload.get('search_engine','startpage')}}
    tools=Tools()
    agent=BrowserAgent(tool_registry=tools,planner=lambda *_:pytest.fail('Engine preferences do not need a page planner'))
    assert agent.can_handle(message)
    result=agent.answer(message)
    assert result.status=='answered'
    assert 'browser.session.open' not in [name for name,_ in tools.calls]
    assert ('DuckDuckGo' if 'DuckDuckGo' in message else 'Brave' if 'Brave' in message else 'Startpage') in result.summary


def test_engine_capability_accepts_only_engine_selection(monkeypatch):
    from agent.tools.capabilities import browser_service
    from agent.contracts.browser import BrowserStatus
    calls=[]
    monkeypatch.setattr(browser_service,'browser_session',lambda op,payload=None:calls.append((op,payload)) or BrowserStatus(available=True))
    registry=browser_service.BrowserCapabilityService().build_registry()
    registry.invoke('browser.session.search_engine',{'search_engine':'brave'},agent_name='BrowserAgent')
    assert calls==[('control',{'operation':'preferences','search_engine':'brave'})]
    with pytest.raises(ValueError):
        registry.invoke('browser.session.search_engine',{'search_engine':'bing'},agent_name='BrowserAgent')
    with pytest.raises(ValueError):
        registry.invoke('browser.session.search_engine',{'search_engine':'google','agent_enabled':False},agent_name='BrowserAgent')


def test_resize_during_planning_does_not_discard_a_navigation_without_element_refs():
    from test_browser_agent import BrowserTools
    class Tools(BrowserTools):
        revision='before'
        def invoke(self,*args,**kwargs):
            result=super().invoke(*args,**kwargs)
            if args[0].startswith('browser.session'):
                result.update(snapshot_id=self.revision,active_tab_id='tab')
            return result
    tools=Tools()
    def planner(*_):
        if not any(name=='browser_navigate' for name,*_ in tools.calls):
            tools.revision += '-resized'
            return {'action':'navigate','url':'https://www.wikipedia.org/'}
        return {'action':'done','summary':'Opened Wikipedia.'}
    result=BrowserAgent(tool_registry=tools,planner=planner).answer('open wikipedia')
    assert result.status=='answered'
    assert sum(name=='browser_navigate' for name,*_ in tools.calls)==1


@pytest.mark.parametrize('message', [
    'open wikipedia and search for the streetfighter moview',
    'open youtube and click on the first video u see',
    'go to reddit and search for mechanical keyboards',
    'visit https://en.wikipedia.org/wiki/Black_hole',
])
def test_page_requests_do_not_require_the_word_browser(message):
    assert BrowserAgent(tool_registry=ToolRegistry()).can_handle(message)


@pytest.mark.parametrize('message', [
    'use the browser to open it', 'i told u already', 'where u are not doing it',
])
def test_browser_retry_keeps_the_concrete_same_thread_user_request(monkeypatch,message):
    from agent import api
    original='open wikipedia and search for the streetfighter moview'
    monkeypatch.setattr(api,'_thread_user_messages',lambda *a,**k:[original,'use the browser to open it',message])
    monkeypatch.setattr(api._live_dispatcher.state_store,'get_pending_action',lambda *_:None)
    assert api._continuity_request(message,'browser-retry') == original


def test_browser_result_is_not_rewritten_by_another_model():
    from agent import api
    from agent.agents.live_dispatcher import LiveAgentResult
    result=LiveAgentResult(handled=True,agent_name='BrowserAgent',status='blocked',answer='The page did not load.')
    assert api._should_passthrough_live_result(result)


def test_chat_model_selection_reaches_the_specialist_with_positional_arguments(monkeypatch):
    import asyncio
    from agent import api
    from agent.llm import providers
    models = tuple(providers.ModelEntry(
        id=model_id, label=model_id, provider='ollama', context=128_000,
        tier='fast', open_weights=True,
    ) for model_id in ('ollama/fixture-default', 'ollama/gemma4:12b'))
    monkeypatch.setattr(providers, 'discover_ollama_models',
        lambda *_: providers.LocalModelInventory(reachable=True, models=models))
    registry = providers.ProviderRegistry()
    registry.set_active('ollama/fixture-default')
    monkeypatch.setattr(providers, 'get_provider_registry', lambda: registry)
    seen=[]
    async def run(*args,**kwargs):
        seen.append(providers.get_provider_registry().current_model().id)
        from types import SimpleNamespace
        return SimpleNamespace(action_receipts=[])
    monkeypatch.setattr(api,'_run_agent_scoped',run)
    asyncio.run(api._run_agent('open wikipedia','model-thread','ollama/gemma4:12b'))
    assert seen==['ollama/gemma4:12b']
    assert registry.current_model().id == 'ollama/fixture-default'


@pytest.mark.parametrize('message', ['what is Wikipedia?', 'how does YouTube work?', 'open the calendar settings', 'play a song on Spotify'])
def test_navigation_match_does_not_capture_questions_or_other_app_actions(message):
    assert not BrowserAgent.is_page_request(message)


def test_browser_retry_does_not_cross_a_new_task(monkeypatch):
    from agent import api
    monkeypatch.setattr(api,'_thread_user_messages',lambda *a,**k:['open wikipedia','play my liked songs','do it'])
    monkeypatch.setattr(api._live_dispatcher.state_store,'get_pending_action',lambda *_:None)
    assert api._continuity_request('do it','other-task')=='do it'


def test_browser_view_shows_agent_cursor_before_the_first_planned_click():
    import asyncio
    from types import SimpleNamespace
    from agent.mcp.dedicated_browser import DedicatedBrowser
    async def check():
        browser=DedicatedBrowser();browser.control='agent';browser.session_id='ready'
        moves=[]
        async def move(x,y): moves.append((x,y))
        async def screenshot(**_): return b'fixture'
        async def send(*_): pass
        async def session(*_): return SimpleNamespace(on=lambda *_:None,send=send)
        browser.active_page=SimpleNamespace(is_closed=lambda:False,viewport_size=browser._viewport,mouse=SimpleNamespace(move=move),screenshot=screenshot)
        browser._pages={'tab':browser.active_page};browser.context=SimpleNamespace(new_cdp_session=session)
        frame=await browser.frame()
        assert frame.pointer is not None, 'The agent cursor must be visible while planning, before any click'
        assert frame.pointer.action=='ready' and moves==[(640,400)]
    asyncio.run(check())


def test_a_changed_control_is_observed_again_without_replaying_the_action():
    from agent.mcp.dedicated_browser import BrowserTargetChanged
    from test_browser_agent import BrowserTools
    class Tools(BrowserTools):
        def invoke(self,name,payload,*,agent_name):
            result=super().invoke(name,payload,agent_name=agent_name)
            if name.startswith('browser.session'):result['preferences']={'agent_interactions':'allow'}
            if name=='browser.routine_action':raise BrowserTargetChanged('This control changed before execution.')
            return result
    tools=Tools()
    steps=iter([{'action':'type','ref':'@e4','text':'streetfighter movie'},
                {'action':'ask','summary':'The page now has a different search field.'}])
    result=BrowserAgent(tool_registry=tools,planner=lambda *_:next(steps)).answer('open wikipedia')
    assert result.status=='blocked' and result.summary=='The page now has a different search field.'
    assert sum(name=='browser_snapshot' for name,*_ in tools.calls)==2
    assert sum(name=='browser.routine_action' for name,*_ in tools.calls)==1


def test_snapshot_recovers_when_the_submitted_search_navigates(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from playwright.async_api import Error
    from agent.mcp.dedicated_browser import DedicatedBrowser
    async def check():
        browser=DedicatedBrowser();reads=[]
        async def loaded(*_,**__): pass
        browser.active_page=SimpleNamespace(wait_for_load_state=loaded)
        async def collect(full):
            reads.append(True)
            if len(reads)==1:raise Error('Execution context was destroyed, most likely because of a navigation')
            return 'Page: Search results',{},{}
        monkeypatch.setattr(browser,'_collect_snapshot',collect)
        assert await browser.snapshot(full=True)=='Page: Search results'
        assert len(reads)==2 and browser.snapshot_id
    asyncio.run(check())


def test_late_navigation_refreshes_the_plan_without_replaying_the_old_click():
    from test_browser_agent import BrowserTools
    class Tools(BrowserTools):
        snapshot_id='first'
        def invoke(self,name,payload,*,agent_name):
            result=super().invoke(name,payload,agent_name=agent_name)
            if name.startswith('browser.session'):result['snapshot_id']=self.snapshot_id
            return result
    tools=Tools();plans=[]
    def plan(*_):
        plans.append(True)
        if len(plans)==1:
            tools.snapshot_id='navigated'
            return {'action':'click','ref':'@e15'}
        return {'action':'done','summary':'The refreshed search results are visible.'}
    result=BrowserAgent(tool_registry=tools,planner=plan).answer('open wikipedia')
    assert result.status=='answered'
    assert sum(name=='browser_snapshot' for name,*_ in tools.calls)==2
    assert not any(name=='browser.routine_action' for name,*_ in tools.calls)


def test_search_request_finishes_on_observed_results_instead_of_clicking_again():
    from test_browser_agent import BrowserTools
    class Tools(BrowserTools):
        def invoke(self,name,payload,*,agent_name):
            result=super().invoke(name,payload,agent_name=agent_name)
            if name.startswith('browser.session'):result['preferences']={'agent_interactions':'allow'}
            if name=='browser.routine_action':
                if payload['params']['action']=='type':
                    return {'observation':'Page: Wikipedia\nURL: https://www.wikipedia.org/\n@e11 input Search (search) value="streetfighter movie"'}
                return {'observation':'Page: streetfighter movie - Search results - Wikipedia\nURL: https://en.wikipedia.org/wiki/Special:Search?search=streetfighter+movie\n@e25 a Street Fighter (1994 film)'}
            return result
    tools=Tools()
    steps=iter([{'action':'type','ref':'@e11','text':'streetfighter movie'}, {'action':'click','ref':'@e13'}])
    result=BrowserAgent(tool_registry=tools,planner=lambda *_:next(steps)).answer('open wikipedia and search for the streetfighter moview')
    assert result.status=='answered' and 'streetfighter movie' in result.summary
    assert sum(name=='browser.routine_action' for name,*_ in tools.calls)==2


@pytest.mark.parametrize('goal,query', [
    ('open wikipedia and search for a movie then click its first result','movie'),
    ('open wikipedia and search for a movie then read it','movie'),
    ('open wikipedia and search for a movie','different-query'),
])
def test_search_completion_requires_matching_observation_and_no_remaining_actions(goal,query):
    observation='Page: movie - Search results - Example\nURL: https://example.com/?q='+query
    assert not BrowserAgent._site_search_complete(goal,observation,'movie')
