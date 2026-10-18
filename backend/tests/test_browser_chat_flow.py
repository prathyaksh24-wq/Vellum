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
    'search Wikipedia for Jailer 2',
    'search for Jailer 2 on Wikipedia',
    'can u search YouTube for black holes',
])
def test_page_requests_do_not_require_the_word_browser(message):
    assert BrowserAgent(tool_registry=ToolRegistry()).can_handle(message)


@pytest.mark.parametrize('message',['what is Jailer 2 about?','search for the latest Google product news','look up Jailer 2'])
def test_factual_queries_do_not_force_a_browser_from_a_site_keyword(message):
    assert not BrowserAgent(tool_registry=ToolRegistry()).can_handle(message)


def test_search_followups_stay_with_an_established_browser_task():
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    dispatcher=LiveAgentDispatcher.__new__(LiveAgentDispatcher)
    assert dispatcher._is_contextual_followup('now search for NBA','BrowserAgent')
    assert dispatcher._is_contextual_followup('click the first result','BrowserAgent')
    assert not dispatcher._is_contextual_followup('what is Jailer 2 about?','BrowserAgent')


def test_browser_search_followup_precedes_topic_match_but_facts_can_change_agent(tmp_path):
    from agent.agents.base import SpecialistResponse
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.state import MasterThreadStateStore
    from agent.profiles import AgentCatalog

    class Browser:
        name = 'BrowserAgent'
        def can_handle(self, query): return False
        def answer(self, query):
            return SpecialistResponse(agent=self.name, status='answered', summary='Searched the current page.')

    class Sports(Browser):
        name = 'SportsAgent'
        def can_handle(self, query): return 'NBA' in query

    state = MasterThreadStateStore(sessions_db=tmp_path / 'sessions.db')
    catalog = AgentCatalog(profile_dir=tmp_path / 'profiles', executors={'BrowserAgent': Browser(), 'SportsAgent': Sports()})
    dispatcher = LiveAgentDispatcher(vault_root=tmp_path, agent_catalog=catalog, state_store=state)
    state.set_active_agent('browser-followup', 'BrowserAgent')
    result = dispatcher.maybe_handle('now search for NBA', 'browser-followup')
    assert result.agent_name == 'BrowserAgent' and result.route_source == 'contextual'
    result = dispatcher.maybe_handle('Who won the NBA game?', 'browser-followup')
    assert result.agent_name == 'SportsAgent'


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
    from agent.llm.providers import get_provider_registry
    seen=[]
    async def run(*args,**kwargs):
        seen.append(get_provider_registry().current_model().id)
        from types import SimpleNamespace
        return SimpleNamespace(action_receipts=[])
    monkeypatch.setattr(api,'_run_agent_scoped',run)
    asyncio.run(api._run_agent('open wikipedia','model-thread','ollama/gemma4:12b'))
    assert seen==['ollama/gemma4:12b']


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
    result=BrowserAgent(tool_registry=tools,planner=lambda *_:next(steps)).answer('open wikipedia and search for the streetfighter moview, show the search results')
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


def test_search_types_into_the_page_and_clicks_a_suggestion_instead_of_guessing_an_article_url():
    from test_browser_agent import BrowserTools
    class Tools(BrowserTools):
        url='about:blank'
        text=''
        def observation(self):
            if '/wiki/Jailer_2' in self.url:return 'Page: Jailer 2 - Wikipedia\nURL: '+self.url
            return ('Page: Wikipedia\nURL: '+self.url+'\n@e1 input Search Wikipedia (search) value="'+self.text+'"'
                    +'\n@e2 a Jailer 2 (link) https://en.wikipedia.org/wiki/Jailer_2')
        def invoke(self,name,payload,*,agent_name):
            result=super().invoke(name,payload,agent_name=agent_name)
            if name=='browser.session.permission':return {'permission':'allow'}
            if name.startswith('browser.session'):
                result.update(preferences={'agent_interactions':'allow'},tabs=[{'active':True,'url':self.url}])
            elif name=='browser_snapshot':return self.observation()
            elif name=='browser_navigate':self.url=payload['url'];return self.observation()
            elif name=='browser.routine_action':
                if payload['params']['action']=='type':self.text=payload['params']['text']
                elif payload['params']['action']=='click':self.url='https://en.wikipedia.org/wiki/Jailer_2'
                return {'observation':self.observation()}
            return result
    tools=Tools()
    steps=iter([{'action':'navigate','url':'https://en.wikipedia.org/wiki/Jailer_2'},
                {'action':'navigate','url':'https://www.wikipedia.org/'},
                {'action':'type','ref':'@e1','text':'jailer'},
                {'action':'click','ref':'@e2'}, {'action':'done','summary':'Opened the observed Jailer 2 suggestion.'}])
    result=BrowserAgent(tool_registry=tools,planner=lambda *_:next(steps)).answer('Use the browser to search for Jailer 2 on Wikipedia')
    assert result.status=='answered'
    assert [payload['url'] for name,payload,_ in tools.calls if name=='browser_navigate']==['https://www.wikipedia.org/']
    assert [payload['params']['action'] for name,payload,_ in tools.calls if name=='browser.routine_action']==['type','click']


def test_search_cannot_claim_completion_without_a_visible_search():
    from test_browser_agent import BrowserTools
    tools=BrowserTools()
    result=BrowserAgent(tool_registry=tools,planner=lambda *_:{'action':'done','summary':'Found Jailer 2.'}).answer('Search for Jailer 2 on Wikipedia')
    assert result.status=='blocked'


def test_search_can_open_an_explicit_user_url_without_retyping_it():
    from test_browser_agent import BrowserTools
    tools=BrowserTools()
    steps=iter([{'action':'navigate','url':'https://en.wikipedia.org/wiki/Jailer_2'}, {'action':'done','summary':'Opened the supplied page.'}])
    result=BrowserAgent(tool_registry=tools,planner=lambda *_:next(steps)).answer('Search this page https://en.wikipedia.org/wiki/Jailer_2')
    assert result.status=='answered'
    assert any(name=='browser_navigate' for name,*_ in tools.calls)


def test_each_successful_action_resets_the_changing_control_retry_budget():
    from test_browser_agent import BrowserTools
    from agent.mcp.dedicated_browser import BrowserTargetChanged
    class Tools(BrowserTools):
        attempts={}
        completed=[]
        def invoke(self,name,payload,*,agent_name):
            result=super().invoke(name,payload,agent_name=agent_name)
            if name.startswith('browser.session'):result['preferences']={'agent_interactions':'allow'}
            if name=='browser.routine_action':
                action=payload['params']['action'];self.attempts[action]=self.attempts.get(action,0)+1
                if self.attempts[action]==1:raise BrowserTargetChanged('The control changed before execution.')
                self.completed.append(action)
                return {'observation':'Observed input Search value="jailer"'}
            return result
    tools=Tools()
    steps=[{'action':'type','ref':'@e1','text':'jailer'}, {'action':'click','ref':'@e2'},
           {'action':'press_key','key':'Enter'}, {'action':'done','summary':'Opened the observed result.'}]
    result=BrowserAgent(tool_registry=tools,planner=lambda *_:steps[len(tools.completed)]).answer('Search for Jailer 2 on Wikipedia')
    assert result.status=='answered'
    assert tools.completed==['type','click','press_key']


def test_named_page_lookup_keeps_planning_from_results_so_it_can_click_the_article():
    observation='Page: Jailer 2 - Search results - Wikipedia\nURL: https://en.wikipedia.org/w/index.php?search=Jailer+2'
    assert not BrowserAgent._site_search_complete('Search for Jailer 2 on Wikipedia',observation,'Jailer 2')


@pytest.mark.parametrize('step',[{'action':'navigate','url':'https://www.google.com/'},
                                {'action':'tabs','tab_action':'new','url':'https://www.google.com/'}])
def test_an_already_open_address_is_not_reloaded_or_duplicated(step):
    from test_browser_agent import BrowserTools
    class Tools(BrowserTools):
        def invoke(self,name,payload,*,agent_name):
            result=super().invoke(name,payload,agent_name=agent_name)
            if name.startswith('browser.session'):result['tabs']=[{'active':True,'url':'https://www.google.com'}]
            return result
    tools=Tools();steps=iter([step,{'action':'done','summary':'Google is already open.'}])
    result=BrowserAgent(tool_registry=tools,planner=lambda *_:next(steps)).answer('Open Google')
    assert result.status=='answered'
    assert not any(name in {'browser_navigate','browser_tabs'} for name,*_ in tools.calls)
