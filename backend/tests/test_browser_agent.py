import json
from types import SimpleNamespace
import pytest

from agent.agents.browser import BrowserAgent, LocalBrowserPlanner
from agent.app_actions import browser as browser_actions
from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.contracts.browser import BrowserControl, BrowserStatus
from agent.mcp.dedicated_browser import navigation_url
from agent.profiles import AgentCatalog, profile_policy
from agent.tools.capabilities.browser_service import BrowserCapabilityService
from agent.tools.registry import ToolPermissionError


class BrowserTools:
    def __init__(self):
        self.calls = []
        self.control = 'agent'
    def invoke(self, name, payload, *, agent_name):
        self.calls.append((name, payload, agent_name))
        if name.startswith('browser.session'):
            return {'control':self.control, 'snapshot_id':'snapshot-1', 'downloads':[]}
        if name == 'browser_snapshot':
            return 'UNTRUSTED: @e1 a Local page http://localhost/page'
        return 'Observed success'


def test_browser_agent_uses_shared_tools_and_never_replays_cached_actions():
    tools = BrowserTools()
    steps = iter([{'action':'navigate','url':'https://example.com'}, {'action':'done','summary':'Read the actual page.'}])
    agent = BrowserAgent(tool_registry=tools, planner=lambda *args: next(steps))
    response = agent.answer('Open example.com')
    assert response.status == 'answered'
    assert ('browser_navigate', {'url':'https://example.com'}, 'BrowserAgent') in tools.calls
    profile = AgentCatalog().get('BrowserAgent')
    assert profile.memory.cache_first is False
    assert profile.cache.default_ttl_seconds == 0


def test_browser_agent_proposes_click_and_executes_only_stored_confirmation():
    tools = BrowserTools()
    steps = iter([{'action':'click','ref':'@e1','summary':'Open the selected link'}, {'action':'done','summary':'Opened it.'}])
    agent = BrowserAgent(tool_registry=tools, planner=lambda *args: next(steps))
    pending = agent.answer('Open the selected link')
    assert pending.status == 'blocked'
    assert not any(name == 'browser_click' for name, *_ in tools.calls)
    assert pending.action_request['payload']['snapshot_id'] == 'snapshot-1'
    response = agent.execute_action_request(pending.action_request)
    assert response.status == 'answered'
    assert next(payload for name, payload, _ in tools.calls if name == 'browser.confirmed_action')['confirm'] is True


def test_pause_yields_before_planning():
    tools = BrowserTools()
    tools.control = 'user'
    agent = BrowserAgent(tool_registry=tools, planner=lambda *_: pytest.fail('Must not plan after takeover'))
    assert agent.answer('Download this').status == 'blocked'
    assert len(tools.calls) == 1


def test_browser_registry_and_profile_deny_main_and_other_agents():
    registry = BrowserCapabilityService().build_registry()
    for name in registry.names():
        with pytest.raises(ToolPermissionError):
            registry.invoke(name, {}, agent_name='VellumAgent')
    with pytest.raises(ToolPermissionError):
        registry.invoke('browser_click', {'ref':'e1'}, agent_name='BrowserAgent')
    with profile_policy(profile_id='BrowserAgent', allowed_tools=frozenset(), allowed_skills=frozenset(), require_confirmation=frozenset()):
        with pytest.raises(ToolPermissionError):
            registry.invoke('browser.session.status', {}, agent_name='BrowserAgent')


@pytest.mark.parametrize('url', ['file:///C:/secret.txt','javascript:alert(1)','data:text/html,test','https://user:secret@example.com','example.com'])
def test_navigation_rejects_non_web_and_credential_urls(url):
    with pytest.raises(ValueError):
        navigation_url(url)


def test_controls_reject_arbitrary_paths_and_commands():
    with pytest.raises(ValueError):
        BrowserControl(operation='show_download', path='C:/secret.txt')
    with pytest.raises(ValueError):
        BrowserControl(operation='evaluate', text='malicious()')


def test_control_receipt_excludes_typed_text_and_browser_content(monkeypatch):
    monkeypatch.setattr(browser_actions, 'browser_session', lambda *_: BrowserStatus(available=True, running=True, control='user', session_id='abc'))
    runtime = AppActionRuntime()
    receipt = runtime.dispatch(AppActionRequest(action_id='browser.session.control', arguments={'operation':'type','text':'private-field-value','frame_id':'abc'}), AppActionContext(source='ui'))
    assert receipt.status == 'applied'
    assert 'private-field-value' not in receipt.model_dump_json()
    invalid = runtime.dispatch(AppActionRequest(action_id='browser.session.control', arguments={'operation':'type', 'text':'private-field-value', 'x':'private-field-value'}), AppActionContext(source='ui'))
    assert invalid.status == 'failed' and 'private-field-value' not in invalid.model_dump_json()
    denied = runtime.dispatch(AppActionRequest(action_id='browser.session.control', arguments={'operation':'take_over'}), AppActionContext(source='nlp'))
    assert denied.status == 'failed'


def test_panel_content_uses_workspace_layout_contract():
    runtime = AppActionRuntime()
    receipt = runtime.dispatch(AppActionRequest(action_id='ui.surface.configure', arguments={'reference':'right-panel', 'visible':True, 'properties':{'content':'browser'}}), AppActionContext(source='ui'))
    assert receipt.status == 'applied'


def test_local_planner_rejects_cloud_before_page_disclosure(monkeypatch):
    from agent.llm import providers
    monkeypatch.setattr(providers, 'get_provider_registry', lambda: SimpleNamespace(refresh_local_models=lambda:None, current_model=lambda:SimpleNamespace(id='openai/gpt-4.1')))
    with pytest.raises(ValueError, match='local model'):
        LocalBrowserPlanner()('Read this', 'private page text', [])


def test_main_delegation_routes_bounded_context_to_browser_profile(tmp_path):
    from test_delegation_runtime import build_runtime
    from agent.master.runtime import DelegationRequest
    runtime, _clock = build_runtime(tmp_path)
    profile = AgentCatalog().get('BrowserAgent')
    tools = BrowserTools()
    observed = []
    agent = BrowserAgent(tool_registry=tools, planner=lambda goal, *_: observed.append(goal) or {'action':'done','summary':'Observed the requested page.'})
    runtime.agent_catalog = AgentCatalog(profile_dir=tmp_path/'browser-profiles', builtins={'BrowserAgent':profile}, executors={'BrowserAgent':agent})
    result = runtime.delegate(DelegationRequest(agent_id='BrowserAgent', task='Read the requested page.', context='User-selected URL: https://example.com', parent_thread_id='main-chat'))
    assert result.profile_id == 'BrowserAgent' and result.response.status == 'answered'
    assert observed == ['Read the requested page.\n\nUser-provided task context:\nUser-selected URL: https://example.com']
    assert result.cache_status != 'hit'
    assert all(owner == 'BrowserAgent' for _, _, owner in tools.calls)


def test_main_core_tools_do_not_expose_browser_integration():
    from agent.graph.agent import core_tool_registry
    assert not any(name.startswith('browser_') or name.startswith('browser.') for name in core_tool_registry().names())


def test_takeover_during_planning_prevents_next_action():
    tools = BrowserTools()
    def planner(*_):
        tools.control = 'user'
        return {'action':'navigate','url':'https://example.com'}
    assert BrowserAgent(tool_registry=tools, planner=planner).answer('Read example.com').status == 'blocked'
    assert not any(name == 'browser_navigate' for name, *_ in tools.calls)


@pytest.mark.parametrize('confirmation', ['confirm', 'cancel'])
def test_browser_interaction_uses_main_pending_action_authority(tmp_path, confirmation):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.runtime import DelegationRequest
    from agent.master.state import MasterThreadStateStore
    tools = BrowserTools()
    steps = iter([{'action':'click','ref':'@e1','summary':'Open the selected page'}, {'action':'done','summary':'Opened the page.'}])
    agent = BrowserAgent(tool_registry=tools, planner=lambda *_: next(steps))
    catalog = AgentCatalog(profile_dir=tmp_path/'profiles', executors={'BrowserAgent':agent})
    state = MasterThreadStateStore(sessions_db=tmp_path/'sessions.db')
    dispatcher = LiveAgentDispatcher(vault_root=tmp_path, agent_catalog=catalog, state_store=state)
    pending = dispatcher.maybe_handle('Open the selected browser tab link', 'browser-thread')
    assert 'Confirm' in pending.answer
    assert state.get_pending_action('browser-thread')['payload']['snapshot_id'] == 'snapshot-1'
    result = dispatcher.maybe_handle(confirmation, 'browser-thread')
    writes = [payload for name, payload, _ in tools.calls if name == 'browser.confirmed_action']
    assert bool(writes) == (confirmation == 'confirm')
    assert result.status == ('answered' if confirmation == 'confirm' else 'blocked')
    replay = dispatcher.delegation_runtime.delegate(DelegationRequest(agent_id='BrowserAgent', task='confirm', parent_thread_id='browser-thread', confirm_pending_action=True))
    assert replay.response.status == 'blocked'
    assert len([name for name, *_ in tools.calls if name == 'browser.confirmed_action']) == len(writes)
