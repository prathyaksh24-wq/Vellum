import time
import asyncio
import json
import threading
from types import SimpleNamespace
import pytest

from agent.agents.youtube import YoutubeAgent
from agent.contracts.music import MusicPlan, MusicPlaylistCreateProposal
from agent.plugins.youtube_intelligence import _query_terms
from agent.tools.capabilities.spotify_service import SpotifyCapabilityService
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
from test_music_agent import fixture_agent


def test_watched_creator_request_never_uses_public_search(tmp_path):
    calls = []
    service = YoutubeCapabilityService(vault_root=tmp_path,
        search_backend=lambda *a: calls.append('public') or [],
        takeout_history_backend=lambda *a: pytest.fail('Current history must not use an archive'),
        browser_history_backend=lambda: {'available':True,'total':1,'items':[
            {'title':'A watched video','channel_title':'Jynxzi Live','video_id':'abcdefghijk'}]})
    response = YoutubeAgent(tmp_path, youtube_service=service).answer('what videos have i watched from jynxzi')
    assert calls == []
    assert 'A watched video' in response.summary


def test_explain_is_not_a_channel_filter():
    assert _query_terms('explain my YT data') == set()


def test_skip_seconds_seeks_instead_of_advancing():
    plan = fixture_agent()[0]._fast_plan('skip 30 secs')
    assert plan is not None and plan.operation == 'seek'
    assert plan.seek_delta_ms == 30000


def test_yes_accepts_single_song_suggestion_without_replanning():
    agent, _, calls = fixture_agent(tracks=[{'name':'Crazy in Love','uri':'spotify:track:one',
        'artists':[{'name':'Beyoncé'},{'name':'JAY-Z'}]}])
    context={'last_plan':{'operation':'play_song','query':'Crazy in Love'},'at':time.time(),
        'choices':[{'title':'Crazy in Love','artist':'Beyoncé, JAY-Z'}]}
    assert agent.can_handle_with_context('yes', context)
    response=agent.answer_with_context('yes', context)
    assert response.status == 'answered'
    assert any(n=='spotify_playback' for n,_ in calls)


def test_repeated_catalog_versions_do_not_create_duplicate_questions():
    track={'name':'Crazy in Love','artists':[{'name':'Beyoncé'},{'name':'JAY-Z'}]}
    agent, _, calls=fixture_agent(tracks=[{**track,'uri':'spotify:track:a'},{**track,'uri':'spotify:track:b'}])
    choice=agent.answer('play Crazzy in Love')
    assert len(choice.structured_payload['choices'])==1
    assert 'Reply yes' in choice.summary
    context=agent.thread_context(choice,{})
    response=agent.answer_with_context('yes',context)
    assert response.status=='answered'
    assert sum(n=='spotify_playback' for n,_ in calls)==1


def test_playlist_success_requires_readback():
    proposal=MusicPlaylistCreateProposal(provider='spotify', name='Verified',
        songs=[{'title':'Song','uri':'spotify:track:one'}])
    def invoke(name, args):
        return {'id':'new'} if args['action']=='create' else {}
    import pytest
    with pytest.raises(ValueError, match='verif|confirm'):
        SpotifyCapabilityService().create_playlist(proposal, invoke)


@pytest.mark.parametrize('text', ['what is playing right now', 'which podcast is playing', 'what am I listening to'])
def test_current_audio_always_reads_live_state(text):
    agent, _, _ = fixture_agent()
    assert agent.can_handle(text)
    assert agent._fast_plan(text).operation == 'current'
    def invoke(name, args):
        assert args == {'action':'get_state'}
        return {'is_playing':True,'track':{'name':'A current JRE episode'},'artists':['The Joe Rogan Experience']}
    answer = SpotifyCapabilityService().execute(agent._fast_plan(text), invoke)
    assert 'JRE episode' in answer and 'Joe Rogan' in answer and 'Classics' not in answer


def test_seek_is_relative_and_clamped_before_episode_end():
    calls=[]
    progress=90000
    def invoke(name, args):
        nonlocal progress
        calls.append(args)
        if args['action']=='seek':
            progress=args['position_ms']
        return {'track':{'name':'episode'},'progress_ms':progress,'duration_ms':100000}
    SpotifyCapabilityService().execute(MusicPlan(operation='seek',seek_delta_ms=30000), invoke)
    assert calls == [{'action':'get_state'}, {'action':'seek','position_ms':99000}, {'action':'get_state'}]


@pytest.mark.parametrize('text', ['can post something abput ur self on X', 'i meant post something about ur self on x'])
def test_natural_x_self_post_drafts_instead_of_searching(tmp_path, text):
    from agent.agents.x_agent import XAgent
    calls=[]
    agent=XAgent(tmp_path, post_drafter=lambda request:calls.append(request) or 'I am Vellum, your personal assistant.')
    assert agent.can_handle(text)
    result=agent.answer_with_context(text,{})
    assert calls and result.action_request['action']=='x.publish_post'
    assert len(result.summary) < 200


def build_parallel_dispatcher(tmp_path, barrier=None, release=None):
    from agent.agents.base import SpecialistResponse
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.runtime import DelegationRuntime
    from agent.master.state import MasterThreadStateStore
    from agent.profiles import AgentCatalog
    class Executor:
        def __init__(self, name, word): self.name, self.word=name,word
        def can_handle(self, query): return self.word in query.lower()
        def answer(self, query):
            if barrier: barrier.wait(timeout=3)
            if self.name=='CalendarAgent' and release: assert release.wait(3)
            return SpecialistResponse(agent=self.name,status='answered',summary=self.name+' result')
    catalog=AgentCatalog(profile_dir=tmp_path/'profiles',executors={
        'YoutubeAgent':Executor('YoutubeAgent','watched'), 'CalendarAgent':Executor('CalendarAgent','calendar')})
    state=MasterThreadStateStore(sessions_db=tmp_path/'sessions.db')
    runtime=DelegationRuntime(agent_catalog=catalog,memory_orchestrator=None,pending_action_store=state,audit_path=tmp_path/'audit.jsonl')
    return LiveAgentDispatcher(vault_root=tmp_path,agent_catalog=catalog,state_store=state,delegation_runtime=runtime)


def test_independent_specialists_run_concurrently_and_emit_fast_result(tmp_path):
    release=threading.Event()
    dispatcher=build_parallel_dispatcher(tmp_path,threading.Barrier(2),release)
    seen=[]
    def emit(part):
        seen.append(part.agent_name)
        if part.agent_name=='YoutubeAgent':
            assert not release.is_set()
            release.set()
    result=dispatcher.maybe_handle('what videos have I watched and show my calendar', 'parallel', on_result=emit)
    assert seen==['YoutubeAgent','CalendarAgent']
    assert result.answer == 'YoutubeAgent result\n\nCalendarAgent result'


def test_dependent_tasks_do_not_start_concurrently(tmp_path):
    dispatcher=build_parallel_dispatcher(tmp_path)
    assert dispatcher._independent_tasks('what videos have I watched then add that to my calendar','dependent') == []


def test_natural_other_agent_request_preserves_explicit_agent_selection(tmp_path):
    dispatcher=build_parallel_dispatcher(tmp_path)
    dispatcher.state_store.set_active_agent('selected','CalendarAgent',selected=True)
    result=dispatcher.maybe_handle('what videos have I watched','selected')
    assert result.agent_name=='YoutubeAgent'
    assert dispatcher.state_store.get('selected').active_agent=='CalendarAgent'


def test_combined_watch_history_and_skip_uses_existing_action_boundary(monkeypatch):
    from agent.app_actions.runtime import AppActionRuntime
    from agent.plugins import spotify_controls
    monkeypatch.setattr(spotify_controls,'spotify_client',lambda:SimpleNamespace(web_playback_status=lambda:{'status':'disabled'}))
    runtime=AppActionRuntime()
    runtime._plugin_contributions=SimpleNamespace(action_available=lambda *a:True)
    turn=runtime.plan_submission('what videos have i watched from jynxzi and also skip the song')
    assert len(turn.actions)==1
    assert turn.actions[0].arguments == {'action':'next'}
    assert turn.conversation_message=='what videos have i watched from jynxzi'


@pytest.mark.asyncio
async def test_combined_action_answer_contains_real_receipt_once(monkeypatch):
    from agent import api
    from agent.app_actions.runtime import AppActionRuntime
    from agent.plugins import spotify_controls
    from test_app_action_stream import parse_sse
    runtime=AppActionRuntime()
    runtime._plugin_contributions=SimpleNamespace(action_available=lambda *a:True)
    calls=[]
    receipt=SimpleNamespace(status='applied',result={},message='Skipped to the next track.',
        model_dump=lambda **kwargs:{'status':'applied','action_id':'spotify.playback.control'})
    monkeypatch.setattr(runtime,'dispatch_many',lambda actions,ctx:calls.extend(actions) or [receipt])
    monkeypatch.setattr(api,'_app_action_runtime',runtime)
    monkeypatch.setattr(spotify_controls,'spotify_client',lambda:SimpleNamespace(web_playback_status=lambda:{'status':'disabled'}))
    async def stream(**kwargs):
        assert kwargs['clean_message']=='what videos have I watched from Jynxzi'
        yield api._response_created(response_id='parallel',thread_id='qa-mixed')
        yield api._sse('token',{'text':'Your watched videos.'})
        yield api._sse('final',{'answer':'Your watched videos.'})
        yield api._response_completed(response_id='parallel',thread_id='qa-mixed',answer='Your watched videos.',tools=[],sources=[])
    monkeypatch.setattr(api,'_stream_agent_turn',stream)
    async def passthrough(events,audit):
        async for event in events: yield event
    monkeypatch.setattr(api,'_audited_turn_stream',passthrough)
    response=await api.chat_stream(api.ChatRequest(message='what videos have I watched from Jynxzi and also skip the song',thread_id='qa-mixed',store=False))
    events=parse_sse(''.join([chunk async for chunk in response.body_iterator]))
    tokens=''.join(data['text'] for name,data in events if name=='token')
    final=next(data['response']['output_text'] for name,data in events if name=='response.completed')
    assert tokens==final=='Skipped to the next track.\n\nYour watched videos.'
    assert len(calls)==1


@pytest.mark.asyncio
async def test_stream_shows_finished_specialist_before_slow_specialist_finishes(tmp_path, monkeypatch):
    from agent import api
    release=threading.Event()
    dispatcher=build_parallel_dispatcher(tmp_path,threading.Barrier(2),release)
    monkeypatch.setattr(api,'_live_dispatcher',dispatcher)
    monkeypatch.setattr(api,'_continuity_request',lambda message,thread:message)
    monkeypatch.setattr(api,'_is_memory_recall_request',lambda *a:False)
    monkeypatch.setattr(api,'_is_explanation_followup',lambda *a:False)
    monkeypatch.setattr(api,'_conversation_context_store',SimpleNamespace(resolve=lambda *a,**k:{'context':'','attachments':[]}))
    async def noop(*a,**k): pass
    monkeypatch.setattr(api,'_checkpoint_specialist_exchange',noop)
    chunks=[]
    async for chunk in api._stream_agent_turn(clean_message='what videos have I watched and show my calendar',
            active_thread_id='qa-parallel',model=None,store=False):
        chunks.append(chunk)
        if chunk.startswith('event: token') and 'YoutubeAgent result' in chunk:
            assert not release.is_set()
            release.set()
    assert release.is_set()
    tokens=[json.loads(chunk.split('data: ',1)[1])['text'] for chunk in chunks if chunk.startswith('event: token')]
    assert ''.join(tokens)=='YoutubeAgent result\n\nCalendarAgent result'


def test_creator_filter_reads_beyond_first_page_and_preserves_renames():
    from agent.plugins.youtube_takeout import YouTubeTakeoutImporter
    rows=[{'payload':{'title':'Unrelated','channel_title':'Other','channel_id':'other'},'observed_at':'2026-01-01'} for _ in range(501)]
    rows.extend([{'payload':{'title':'Recent','channel_title':'Jynxzi Live','channel_id':'same'},'observed_at':'2026-01-01'},
        {'payload':{'title':'Old channel alias video','channel_title':'Earlier title','channel_id':'same'},'observed_at':'2025-01-01'}])
    offsets=[]
    class Store:
        def count_observations(self,**kwargs): return len(rows)
        def list_observation_details(self,**kwargs):
            offsets.append(kwargs.get('offset',0))
            return rows[kwargs.get('offset',0):kwargs.get('offset',0)+kwargs['limit']]
    result=YouTubeTakeoutImporter(store=Store(),account_id='test').history(channel='jynxi',limit=5)
    assert offsets==[0,500]
    assert [item['title'] for item in result['items']]==['Recent','Old channel alias video']


def test_personal_synthesis_does_not_send_data_to_cloud():
    from agent.agents.youtube_synthesis import LocalYoutubeSynthesizer
    calls=[]
    synth=LocalYoutubeSynthesizer(model_resolver=lambda:'openai/gpt-4o',model_factory=lambda *a:calls.append(a))
    with pytest.raises(ValueError,match='local'):
        synth('summarize my data',{'channels':[{'label':'Private channel'}]})
    assert calls==[]


def test_personal_synthesis_rejects_unknown_evidence_ids():
    from agent.agents.youtube_synthesis import LocalYoutubeSynthesizer
    class Model:
        def invoke(self,*args,**kwargs):
            assert kwargs['request_timeout'] <= 25
            return SimpleNamespace(content='{"sentences":[{"text":"Invented","evidence_ids":["not-in-packet"]}]}')
    synth=LocalYoutubeSynthesizer(model_resolver=lambda:'ollama/gemma4:12b',model_factory=lambda *a:Model())
    with pytest.raises(ValueError,match='Unsupported'):
        synth('summarize my data',{'channels':[{'label':'A channel'}]})


def test_batch_write_previews_keep_distinct_pending_targets(tmp_path):
    from agent.agents.base import SpecialistResponse
    from agent.master.runtime import DelegationRequest
    dispatcher=build_parallel_dispatcher(tmp_path)
    executed=[]
    for name in ('YoutubeAgent','CalendarAgent'):
        executor=dispatcher.agent_catalog.resolve(name).executor
        executor.answer=lambda query, name=name:SpecialistResponse(agent=name,status='blocked',summary='Confirm '+name,
            action_request={'action':'test.action','preview':name,'payload':{'target':name}})
        executor.execute_action_request=lambda action,name=name:executed.append(action['payload']['target']) or SpecialistResponse(agent=name,status='answered',summary='Done '+name)
    dispatcher.delegation_runtime.delegate_many([
        DelegationRequest(agent_id=name,task='Prepare action',parent_thread_id='batch') for name in ('YoutubeAgent','CalendarAgent')])
    pending=dispatcher.state_store.get_pending_action('batch')
    assert len(pending['queued_actions'])==1
    first=pending['payload']['target']
    dispatcher.maybe_handle('yes','batch')
    assert executed==[first]
    assert dispatcher.state_store.get_pending_action('batch')['payload']['target']!=first
    dispatcher.maybe_handle('yes','batch')
    assert set(executed)=={'YoutubeAgent','CalendarAgent'} and len(executed)==2
    assert dispatcher.state_store.get_pending_action('batch') is None
