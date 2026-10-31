"""Regressions from the saved YouTube feed conversation on 15 October."""
import pytest

from agent.agents.x_agent import XAgent
from agent.agents.youtube import YoutubeAgent
from test_specialist_agents import catalog_for, RecordingRuntime, FixedSkillResolver


@pytest.mark.parametrize('query', [
    'what is youtube feed looking like?',
    'what can u tell me about my youtube feed?',
    'show my yt feed',
])
def test_explicit_youtube_feed_does_not_match_x_first(tmp_path, query):
    catalog = catalog_for({
        'XAgent': XAgent(tmp_path, x_service=object()),
        'YoutubeAgent': YoutubeAgent(tmp_path, youtube_service=object()),
    })
    assert not catalog.resolve('XAgent').executor.can_handle(query)
    assert catalog.match(query).profile.id == 'YoutubeAgent'


@pytest.mark.parametrize('query', [
    'what is youtube feed looking like?',
    'what can u tell me about my youtube feed?',
])
def test_feed_questions_read_saved_creator_feed_before_planning(tmp_path, query):
    calls = []
    class Service:
        def subscription_feed(self, payload):
            calls.append(payload)
            return {'available': True, 'creators': [], 'uploads': [], 'warnings': [],
                'coverage': 'Saved creator uploads only; coverage may be incomplete.'}
    agent = YoutubeAgent(tmp_path, youtube_service=Service(),
        planner=lambda *_: pytest.fail('Saved creator feed should not need a model planner'))
    response = agent.answer(query)
    assert calls == [{}]
    assert response.structured_payload['creator_tracking']['available']


def test_youtube_notifications_are_a_supported_saved_read():
    from agent.contracts.youtube_requests import clear_read_request
    request = clear_read_request('youtube notifications')
    assert request is not None
    assert request.source == 'notifications'


@pytest.mark.parametrize('selected', ['XAgent', 'YoutubeAgent', 'VellumAgent'])
@pytest.mark.parametrize('explicitly_selected', [False, True])
def test_prior_selected_agent_does_not_capture_explicit_youtube_feed(tmp_path, selected, explicitly_selected):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.state import MasterThreadStateStore
    class Service:
        def subscription_feed(self, payload):
            return {'available':True,'creators':[],'uploads':[],
                'coverage':'Saved creator uploads; partial coverage.'}
    catalog=catalog_for({'XAgent':XAgent(tmp_path,x_service=object()),
        'YoutubeAgent':YoutubeAgent(tmp_path,youtube_service=Service())})
    state=MasterThreadStateStore(sessions_db=tmp_path/'sessions.db')
    state.set_active_agent('thread',selected,selected=explicitly_selected)
    runtime=RecordingRuntime(catalog)
    dispatcher=LiveAgentDispatcher(tmp_path,agent_catalog=catalog,state_store=state,
        delegation_runtime=runtime,skill_route_resolver=FixedSkillResolver(None))
    result=dispatcher.maybe_handle('what can u tell me about my youtube feed?',thread_id='thread')
    assert result.agent_name=='YoutubeAgent'
    assert result.tools==['youtube_agent']
    assert runtime.calls[0].agent_id=='YoutubeAgent'
    assert state.get('thread').active_agent==(selected if explicitly_selected else 'YoutubeAgent')


@pytest.mark.parametrize('query', ['show my X feed', 'show my feed', 'post this YouTube video on X'])
def test_explicit_x_and_existing_generic_feed_requests_remain_supported(tmp_path, query):
    assert XAgent(tmp_path,x_service=object()).can_handle(query)


@pytest.fixture
def notification_service(tmp_path,monkeypatch):
    from datetime import datetime,timezone,timedelta
    from agent.automations import api
    from agent.automations.store import AutomationStore
    from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
    store=AutomationStore(tmp_path)
    monkeypatch.setattr(api,'get_store',lambda:store)
    def create(name,builtin_key):
        return store.create(name=name,instructions='Check updates',
            schedule={'kind':'interval','seconds':900},destination={'kind':'notification'},
            builtin=True,builtin_key=builtin_key)
    youtube=create('YouTube creator uploads','youtube_creator_tracking')
    other=create('Other task','other_task')
    now=datetime.now(timezone.utc)
    store.deliver_notification(youtube['id'],'older','Creator: Older saved upload',
        url='https://www.youtube.com/watch?v=older000001',created_at=(now-timedelta(days=2)).isoformat())
    store.deliver_notification(youtube['id'],'recent','Creator: Recent saved upload',
        url='https://www.youtube.com/watch?v=recent00001',created_at=(now-timedelta(minutes=1)).isoformat())
    store.deliver_notification(other['id'],'unrelated','Other task private message',created_at=now.isoformat())
    service=YoutubeCapabilityService(tmp_path,search_backend=lambda *_:pytest.fail('Notification read reached public search'))
    return service,store


def test_saved_notifications_filter_owner_before_limit_and_preserve_read_state(notification_service):
    service,store=notification_service
    registry=service.build_registry()
    recent=registry.invoke('youtube.notifications',{'limit':1},agent_name='YoutubeAgent')
    assert [row['id'] for row in recent['items']]==['recent']
    assert recent['recent_unread_count']==1 and recent['total_count']==2
    history=service.notifications({'view':'history'})
    assert {row['id'] for row in history['items']}=={'older','recent'}
    assert all(row['read_at'] is None for row in history['items'])
    from agent.tools.registry import ToolPermissionError
    with pytest.raises(ToolPermissionError):
        registry.invoke('youtube.notifications',{},agent_name='XAgent')


def test_notification_answer_uses_canonical_inbox_before_planner(notification_service,tmp_path):
    service,store=notification_service
    agent=YoutubeAgent(tmp_path,tool_registry=service.build_registry(),
        planner=lambda *_:pytest.fail('A clear notification question needs no planner'))
    recent=agent.answer_with_context('youtube notifications',{})
    assert recent.status=='answered'
    assert 'Recent saved upload' in recent.summary and 'Older saved upload' not in recent.summary
    assert 'Other task private message' not in recent.summary
    context=agent.thread_context(recent,{})
    link=agent.answer_with_context('give the video link',context)
    assert 'watch?v=recent00001' in link.summary
    history=agent.answer('show my yt notification history')
    assert 'Older saved upload' in history.summary
    assert '2 retained upload notifications' in agent.answer('how many youtube notifications are in my history?').summary


def test_cloud_profile_cannot_read_local_notifications(notification_service):
    from agent.profiles.execution import ProfileExecution,profile_execution
    service,_=notification_service
    context=ProfileExecution('YoutubeAgent','openai:gpt-4.1',None,'','',{},'','thread')
    with profile_execution(context),pytest.raises(ValueError,match='local only'):
        service.notifications({})


@pytest.mark.parametrize('payload',[{'limit':101},{'view':'all'},{'account_id':'other'}])
def test_notification_read_rejects_unsupported_scope_and_bounds(notification_service,payload):
    from pydantic import ValidationError
    service,_=notification_service
    with pytest.raises(ValidationError):
        service.notifications(payload)
