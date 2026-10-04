import pytest

from agent.agents.music import MusicAgent
from agent.contracts.music import MusicPlan
from agent.tools.capabilities.spotify_service import SpotifyCapabilityService


@pytest.mark.parametrize('text, delta', [
    ('move forward 15 sens', 15000),
    ('go back 15 secs', -15000),
    ('move back 30 secs', -30000),
    ('skip 10 secs', 10000),
])
def test_reported_relative_controls_do_not_need_model_planning(text, delta):
    plan = MusicAgent._fast_plan(text)
    assert plan is not None and plan.operation == 'seek'
    assert plan.seek_delta_ms == delta


def test_repeat_current_song_does_not_need_model_planning():
    plan = MusicAgent._fast_plan('put this song on repeat')
    assert plan is not None and plan.operation == 'set_repeat'
    assert plan.repeat_state == 'track'


@pytest.mark.parametrize('text, delta', [
    ('reduce the volume by 30%', -30),
    ('increase the volume by 30%', 30),
])
def test_relative_volume_does_not_need_model_planning(text, delta):
    plan = MusicAgent._fast_plan(text)
    assert plan is not None and plan.operation == 'adjust_volume'
    assert plan.volume_delta_percent == delta


def test_seek_phrases_are_routed_directly_to_music():
    from test_music_agent import fixture_agent
    agent = fixture_agent()[0]
    for text in ('go back 15 secs', 'move forward 15 sens', 'put the current song on repeat', 'reduce the volume by 30%'):
        assert agent.can_handle(text), text


def test_seek_does_not_claim_change_when_spotify_state_never_moves():
    calls = []
    def invoke(name, args):
        calls.append(args)
        if args['action'] == 'get_state':
            return {'track': {'name':'A song', 'uri':'spotify:track:one'},
                    'is_playing':False, 'progress_ms':90000, 'duration_ms':300000}
        return {}
    with pytest.raises(ValueError, match='did not confirm'):
        SpotifyCapabilityService().execute(MusicPlan(operation='seek', seek_delta_ms=-30000), invoke)
    assert sum(call['action']=='seek' for call in calls) == 1


def test_curated_preview_handles_forbidden_public_playlist():
    calls=[]
    def invoke(name,args):
        calls.append(args)
        if name=='spotify_playlists':
            raise ValueError('Spotify request failed with status 403')
        if args['types']==['playlist']:
            return {'playlists':{'items':[{'id':'public','name':'Viral 2026'}]}}
        return {'tracks':{'items':[{'name':'A real song','uri':'spotify:track:'+str(i),'artists':[{'name':'Artist'}]} for i in range(10)]}}
    proposal=SpotifyCapabilityService().curate_playlist(MusicPlan(operation='curate_playlist',query='create a playlist named Test Picks with 2 trendy songs of 2026'),invoke)
    assert len(proposal.songs)==2 and proposal.songs[0].uri=='spotify:track:0'
    assert proposal.name=='Test Picks'
    assert 'not verified' in proposal.description.lower()
    assert all(c.get('action') not in {'create','add_items'} for c in calls)


@pytest.mark.parametrize('query', ['post simething on x','noo i meant post somethign rsndom on x'])
def test_typo_correction_drafts_x_post_without_searching(tmp_path,query):
    from agent.agents.x_agent import XAgent
    agent=XAgent(tmp_path,post_drafter=lambda request:'A short draft.')
    response=agent.answer(query)
    assert response.action_request['payload']['text']=='A short draft.'


@pytest.mark.parametrize('text, operation, query', [
    ('add it to my liked songs','save_current',''),
    ('like this song','save_current',''),
    ('remove this song from my liked songs','remove_current',''),
    ('is this song in my playlist','check_current',''),
    ('is this song in my 2000s bangers playlist','check_current','2000s bangers'),
    ('add it to my Classics playlist','save_current','Classics'),
    ('remove it from my Classics playlist','remove_current','Classics'),
])
def test_current_song_collection_requests_have_typed_fast_plan(text,operation,query):
    plan=MusicAgent._fast_plan(text)
    assert plan is not None and plan.operation==operation
    assert plan.query==query


def test_x_write_timeout_warns_about_uncertain_publication():
    import subprocess
    from agent.tools.capabilities.agent_reach_x_provider import AgentReachXProvider, AgentReachUnconfirmedWriteError
    calls=[]
    def runner(args,**kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired('twitter', kwargs['timeout'])
    with pytest.raises(AgentReachUnconfirmedWriteError,match='check|Check'):
        AgentReachXProvider(runner=runner).post_tweet('Exact test text')
    assert len(calls)==1


def test_repeated_controls_read_fresh_state_and_never_call_planner():
    from agent.tools.registry import ToolRegistry, CapabilityRecord, CapabilityAccess
    calls=[]
    state={'track':{'name':'A song','uri':'spotify:track:one'},'is_playing':False,'progress_ms':90000,'duration_ms':300000,
           'device':{'id':'device','volume_percent':70},'repeat':'off','shuffle':False}
    def run(args):
        calls.append(args)
        if args['action']=='seek': state['progress_ms']=args['position_ms']
        elif args['action']=='set_volume': state['device']['volume_percent']=args['volume_percent']
        elif args['action']=='set_repeat': state['repeat']=args['state']
        elif args['action']=='set_shuffle': state['shuffle']=args['shuffle']
        return {'ok':True,'data':{**state,'device':dict(state['device'])} if args['action']=='get_state' else {}}
    tools=ToolRegistry()
    tools.register(CapabilityRecord(name='spotify_playback',namespace='spotify',access=CapabilityAccess.WRITE,
        allowed_agents=frozenset({'MusicAgent'}),stream_label='Spotify',adapter=run))
    agent=MusicAgent(tool_registry=tools,planner=lambda *_:pytest.fail('Control reached model'),skill_loader=lambda *_:'')
    context={}
    for _ in range(10):
        for text in ('move forward 15 sens','go back 15 secs'):
            response=agent.answer_with_context(text,context)
            assert response.status=='answered'
            context=agent.thread_context(response,context)
    assert state['progress_ms']==90000
    for text in ('reduce the volume by 30%','increase the volume by 30%','put the current song on repeat','repeat off'):
        assert agent.answer(text).status=='answered'
    assert state['device']['volume_percent']==70 and state['repeat']=='off'
    assert sum(c['action']=='seek' for c in calls)==20
    reduced=agent.answer('reduce the volume by 30%')
    context=agent.thread_context(reduced,{})
    assert agent.can_handle_with_context('increase by the same amount',context)
    assert agent.answer_with_context('increase by the same amount',context).status=='answered'
    assert state['device']['volume_percent']==70


def test_x_cli_lock_wait_is_included_in_deadline():
    import time,threading,subprocess
    from agent.tools.capabilities.agent_reach_x_provider import AgentReachXProvider,AgentReachTimeoutError
    calls=[]
    provider=AgentReachXProvider(runner=lambda *args,**kw:calls.append(args) or subprocess.CompletedProcess(args,0,stdout='{}'),timeout_seconds=.01)
    provider._CLI_LOCK.acquire()
    release=threading.Timer(.1,provider._CLI_LOCK.release)
    release.start()
    try:
        started=time.monotonic()
        with pytest.raises(AgentReachTimeoutError):
            provider._exec('user','me','--json')
        assert time.monotonic()-started < .08
        assert calls==[]
    finally:
        release.join()


def test_collection_confirmation_keeps_captured_song_when_playback_changes():
    from agent.contracts.music import MusicCollectionChangeProposal
    saved=set(); calls=[]
    def invoke(name,args):
        calls.append((name,args))
        if args['action']=='get_state':
            return {'track':{'name':'New playing song','uri':'spotify:track:new'}}
        if args['action']=='contains': return {'items':[args['uris'][0] in saved]}
        if args['action']=='save': saved.update(args['uris']); return {}
        pytest.fail('Unexpected tool')
    proposal=MusicCollectionChangeProposal(action='save',collection='liked',track_uri='spotify:track:original',track_title='Original song')
    summary=SpotifyCapabilityService().change_collection(proposal,invoke)
    assert saved=={'spotify:track:original'} and 'Added Original song' in summary
    assert not any(args['action']=='get_state' for _,args in calls)


def test_collection_change_never_claims_unverified_success():
    from agent.contracts.music import MusicCollectionChangeProposal
    calls=[]
    def invoke(name,args):
        calls.append(args)
        return {'items':[False]} if args['action']=='contains' else {}
    proposal=MusicCollectionChangeProposal(action='save',collection='liked',track_uri='spotify:track:one',track_title='A song')
    with pytest.raises(ValueError,match='could not verify'):
        SpotifyCapabilityService().change_collection(proposal,invoke)
    assert sum(c['action']=='save' for c in calls)==1


def test_playlist_membership_reads_later_pages():
    calls=[]
    def invoke(name,args):
        calls.append(args)
        return {'items':[{'item':{'uri':'spotify:track:other'}}]*50,'next':'next'} if args['offset']==0 else {'items':[{'item':{'uri':'spotify:track:one'}}],'next':None}
    assert SpotifyCapabilityService()._playlist_contains('list','spotify:track:one',invoke)
    assert [c['offset'] for c in calls]==[0,50]


def test_x_explicit_target_requests_route_without_main_model(tmp_path):
    from agent.agents.x_agent import XAgent
    agent=XAgent(vault_root=tmp_path,x_service=object())
    assert agent.can_handle('Post "A reliability test." to X')
    assert agent.can_handle('delete https://x.com/i/status/12345')


def test_new_collection_choice_keeps_the_same_music_operation():
    import time
    agent=MusicAgent(tool_registry=object(),integrations={})
    context={'at':time.time(),'last_plan':{'operation':'save_current'},'choices':[{'title':'First playlist','uri':'spotify:playlist:first'},{'title':'Second playlist','uri':'spotify:playlist:second'}]}
    assert agent.can_handle_with_context('2',context)


def test_current_song_collection_shorthand_preserves_domain_context():
    import time
    agent=MusicAgent(tool_registry=object(),integrations={})
    context={'at':time.time(),'last_plan':{'operation':'current'}}
    assert not agent.can_handle('add it to my Classics')
    assert agent.can_handle_with_context('add it to my Classics',context)
    assert agent.can_handle('add this song to my Classics')
    plan=MusicAgent._fast_plan('is this song in any of my playlists')
    assert plan.operation=='check_current' and plan.collection=='playlist' and not plan.query


@pytest.mark.parametrize('text',['play a song','play a random song','put on some music','play something','play music'])
def test_unspecified_music_uses_real_liked_tracks_not_a_literal_title(text):
    plan=MusicAgent._fast_plan(text)
    assert plan.operation=='play_liked' and plan.shuffle is True


def test_unverified_volume_change_retains_the_followup_amount():
    from agent.agents.base import SpecialistResponse
    import time
    agent=MusicAgent(tool_registry=object(),integrations={})
    context=agent.thread_context(SpecialistResponse(agent='MusicAgent',status='error',summary='Unverified',
        structured_payload={'music_plan':MusicPlan(operation='adjust_volume',volume_delta_percent=-30).model_dump()}),{})
    assert agent.can_handle_with_context('increase by the same amount',context)


def test_seek_verification_accepts_delayed_apply_without_accepting_unchanged_position(monkeypatch):
    import time
    now=[0.0]; monkeypatch.setattr(time,'monotonic',lambda:now[0])
    count=[0]
    def invoke(name,args):
        if args['action']=='seek': now[0]=.35; return {}
        count[0]+=1
        if count[0]==1: position=20000
        elif count[0]==2: now[0]=.7; position=20650
        else: now[0]=1.2; position=30400
        return {'is_playing':True,'progress_ms':position,'duration_ms':100000,'track':{'uri':'spotify:track:one'},'device':{'id':'one'}}
    summary=SpotifyCapabilityService().execute(MusicPlan(operation='seek',seek_delta_ms=10000),invoke)
    assert 'Moved forward 10' in summary and count[0]==3


@pytest.mark.parametrize('devices,allows', [([],True),([{'id':'other-device'}],False),(None,False)])
def test_automatic_player_claim_reclaims_only_a_verified_disconnected_device(monkeypatch,devices,allows):
    import time
    from agent.plugins.spotify_runtime import _spotify_module
    client=_spotify_module.tools.SpotifyClient(auth_store=object())
    now=[100.0]; monkeypatch.setattr(time,'monotonic',lambda:now[0])
    client.claim_web_player('old-owner'); client.update_web_player('old-owner','other-device')
    now[0]+=31
    # The old page continues sending heartbeats despite its missing SDK device.
    client.update_web_player('old-owner','other-device')
    monkeypatch.setattr(client,'get_devices',lambda:{'devices':devices})
    if allows:
        assert client.claim_web_player('new-owner')['status']=='connecting'
        with pytest.raises(Exception,match='no longer owns'):
            client.update_web_player('old-owner','other-device')
    else:
        with pytest.raises(Exception,match='another window'):
            client.claim_web_player('new-owner')
