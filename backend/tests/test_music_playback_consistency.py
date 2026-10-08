"""Regressions for continuous suggestions and identity-safe playlist lookup."""
import pytest

from agent.contracts.music import MusicChoiceRequired, MusicPlan
from agent.tools.capabilities.spotify_service import SpotifyCapabilityService
from test_music_agent import fixture_agent


@pytest.mark.parametrize('query,operation', [('mute','mute'),('unmute','unmute'),('go back to the beginning  of the song','restart'),('go back to the beginnign of the song','restart'),('what is the artist name of this song','current')])
def test_mute_restart_and_current_artist_are_direct_controls(query,operation):
    agent,_,_=fixture_agent(planner=lambda *_:pytest.fail('No model acknowledgement for playback or live artist identity'))
    assert agent.can_handle(query)
    assert agent._fast_plan(query).operation==operation


def test_mute_restores_measured_volume_restart_seeks_zero_and_artist_is_live():
    agent,registry,_=fixture_agent(planner=lambda *_:pytest.fail('Use current playback, not prior chat text'))
    volume=[43]; position=[90000]; repeat=['context']; writes=[]
    def invoke(name,args,**kwargs):
        if args['action']=='set_volume':volume[0]=args['volume_percent']; writes.append(args)
        if args['action']=='seek':position[0]=args['position_ms']; writes.append(args)
        if args['action']=='set_repeat':repeat[0]=args['state']; writes.append(args)
        return {'ok':True,'data':{'track':{'name':'Live Song','uri':'spotify:track:one'},'artists':['David Guetta'],
            'progress_ms':position[0],'duration_ms':180000,'is_playing':False,'repeat':repeat[0],'device':{'id':'vellum','volume_percent':volume[0]}}}
    registry.invoke=invoke
    muted=agent.answer('mute'); assert muted.status=='answered' and volume[0]==0
    context=agent.thread_context(muted,{})
    muted_again=agent.answer_with_context('mute',context)
    context=agent.thread_context(muted_again,context)
    unmuted=agent.answer_with_context('unmute',context)
    assert unmuted.status=='answered' and volume[0]==43
    restarted=agent.answer('go back to the beginning of the song')
    assert restarted.status=='answered' and position[0]==0
    artist=agent.answer('what is the artist name of this song')
    assert 'David Guetta' in artist.summary and 'Travis' not in artist.summary
    repeated=agent.answer('put this song on repeat')
    assert repeated.status=='answered' and repeat[0]=='track'
    context=agent.thread_context(repeated,context)
    assert agent.can_handle_with_context('undo it',context)
    undone=agent.answer_with_context('undo it',context)
    assert undone.status=='answered' and repeat[0]=='context'


def test_monthly_listeners_routes_to_main_web_search_even_when_music_is_selected(tmp_path):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.state import MasterThreadStateStore
    from agent.profiles import AgentCatalog
    music,_,_=fixture_agent(planner=lambda *_:pytest.fail('Artist statistics must use public web search'))
    state=MasterThreadStateStore(sessions_db=tmp_path/'sessions.db')
    state.set_active_agent('music','MusicAgent',selected=True)
    dispatcher=LiveAgentDispatcher(vault_root=tmp_path,agent_catalog=AgentCatalog(profile_dir=tmp_path/'profiles',executors={'MusicAgent':music}),state_store=state)
    assert dispatcher.maybe_handle('how many monthly listener does davide guttea have?','music') is None
    from agent import api
    assert api._requests_fresh_public_data('how many monthly listeners does David Guetta have?')
    assert 'web_search' in api._with_forced_web_search_context('how many monthly listeners does David Guetta have?')


def test_failed_repeat_cannot_authorize_undo_and_unmute_cannot_cross_device():
    from agent.agents.music import MusicAgent
    from agent.agents.base import SpecialistResponse
    response=SpecialistResponse(agent='MusicAgent',status='error',summary='Unverified',structured_payload={'music_plan':
        MusicPlan(operation='set_repeat',repeat_state='track',previous_repeat_state='off',repeat_device_id='vellum').model_dump()})
    agent,registry,_=fixture_agent(planner=lambda *_:pytest.fail('Do not guess restoration state'))
    context=MusicAgent.thread_context(response,{})
    assert agent.answer_with_context('undo it',context).status=='needs_fetch'
    writes=[]
    def invoke(name,args,**kwargs):
        if args['action']!='get_state':writes.append(args)
        return {'ok':True,'data':{'device':{'id':'other-device','volume_percent':0}}}
    registry.invoke=invoke
    context['unmuted_volume']={'provider':'spotify','device_id':'vellum','percent':43}
    result=agent.answer_with_context('unmute',context)
    assert result.status=='needs_fetch' and not writes


def test_unmute_without_a_verified_previous_volume_does_not_guess_maximum():
    agent,registry,_=fixture_agent(planner=lambda *_:pytest.fail('No guessed volume'))
    registry.invoke=lambda name,args,**kwargs:{'ok':True,'data':{'device':{'id':'vellum','volume_percent':0}}}
    response=agent.answer('unmute')
    assert response.status=='needs_fetch' and 'no verified pre-mute' in response.summary


@pytest.mark.parametrize('query', ['turn on shuffle','put on the shuffle for this playlsit','turn off shuffle','disable shuffle','increase the volume to max','set volume to maximum'])
def test_shuffle_and_max_volume_wording_has_direct_typed_execution(query):
    agent,_,_=fixture_agent(planner=lambda *_:pytest.fail('A control must not fall through to model acknowledgements'))
    assert agent.can_handle(query)
    plan=agent._fast_plan(query)
    assert plan.operation in {'set_shuffle','set_volume'}
    if plan.operation=='set_volume':assert plan.volume_percent==100
    else:assert plan.shuffle == (not any(word in query for word in ['off','disable']))


def test_truncated_max_volume_request_clarifies_then_accepts_max_correction():
    agent,_,_=fixture_agent(planner=lambda *_:pytest.fail('Never invent a volume change'))
    assert agent.can_handle('increase the volume to ma')
    result=agent.answer('increase the volume to ma')
    assert result.status=='needs_fetch' and 'maximum' in result.summary
    context=agent.thread_context(result,{})
    assert agent.can_handle_with_context('max*',context)
    assert agent._volume_correction('max*',context).volume_percent==100


def test_max_correction_and_shuffle_execute_and_verify_measured_state():
    agent,registry,_=fixture_agent(planner=lambda *_:pytest.fail('Controls must execute in the typed handler'))
    state={'volume':50,'shuffle':False}; writes=[]
    def invoke(name,args,**kwargs):
        if args['action']=='set_volume':state['volume']=args['volume_percent']; writes.append(args)
        if args['action']=='set_shuffle':state['shuffle']=args['shuffle']; writes.append(args)
        return {'ok':True,'data':{'track':{'name':'Song','uri':'spotify:track:one'},'device':{'id':'vellum','volume_percent':state['volume']},'shuffle':state['shuffle']}}
    registry.invoke=invoke
    pending=agent.answer('increase the volume to ma')
    assert not writes
    result=agent.answer_with_context('max*',agent.thread_context(pending,{}))
    assert result.status=='answered' and '50% to 100%' in result.summary
    result=agent.answer('put on the shuffle for this playlsit')
    assert result.status=='answered' and state['shuffle'] is True
    assert [w['action'] for w in writes]==['set_volume','set_shuffle']
    assert agent.answer('increase the volume to max').summary=='Volume is already 100%.'


def test_vague_emoji_request_lists_only_saved_symbol_playlists():
    playlists = [{'id':'one','name':'🔥','uri':'spotify:playlist:one'},
                 {'id':'two','name':'♨︎','uri':'spotify:playlist:two'},
                 {'id':'other','name':'Emoji Hits','uri':'spotify:playlist:other'}]
    agent, _, calls = fixture_agent(playlists=playlists)
    response = agent.answer('play my emoji playlist')
    assert response.status == 'needs_fetch'
    assert {c['uri'] for c in response.structured_payload['choices']} == {'spotify:playlist:one','spotify:playlist:two'}
    assert not any(name == 'spotify_search' or args.get('action') == 'play' for name,args in calls)


@pytest.mark.parametrize('name', ['Tamil','Telugu','Telegu','tamil/telegu'])
def test_language_alias_resolves_saved_combined_playlist(name):
    agent, _, calls = fixture_agent(playlists=[{'id':'mine','name':'Tamil/Telugu Songs','uri':'spotify:playlist:mine'}])
    result = agent.answer('play my ' + name + ' playlist')
    assert result.status == 'answered'
    assert any(args.get('context_uri') == 'spotify:playlist:mine' for _,args in calls)
    assert not any(tool == 'spotify_search' for tool,_ in calls)


def test_missing_personal_playlist_never_searches_other_users_library():
    calls=[]
    def invoke(tool,args):
        calls.append((tool,args))
        return {'items':[], 'next':None}
    with pytest.raises(MusicChoiceRequired):
        SpotifyCapabilityService().resolve_playlist(MusicPlan(operation='play_playlist',query='Tamil'),invoke)
    assert all(tool == 'spotify_playlists' for tool,_ in calls)


def test_accepted_song_suggestion_captures_distinct_continuation_queue():
    tracks=[{'name':'First','uri':'spotify:track:first','artists':[{'name':'Artist'}]},
            {'name':'Second','uri':'spotify:track:second','artists':[{'name':'Artist'}]}]
    agent, _, calls = fixture_agent(tracks=tracks,planner=lambda *_:{'operation':'suggest_music','query':'mellow music'})
    response=agent.answer('suggest a song based on our conversation')
    assert response.action_request
    calls.clear()
    accepted=agent.execute_action_request(response.action_request)
    assert accepted.status == 'answered'
    play=next(args for name,args in calls if args.get('action')=='play')
    assert play['uris'] == ['spotify:track:first','spotify:track:second']
    assert not any(name == 'spotify_search' for name,_ in calls)


def test_live_current_phrase_never_uses_model_or_prior_acknowledgement():
    agent, registry, calls=fixture_agent(planner=lambda *_:pytest.fail('Current song must be read live'))
    def invoke(name,args,**kwargs):
        assert args['action']=='get_state'
        return {'ok':True,'data':{'track':{'name':'Hindi song','uri':'spotify:track:hindi'},'artists':['Artist'],'is_playing':True}}
    registry.invoke=invoke
    result=agent.answer('tell me the song currently playing')
    assert result.status == 'answered' and 'Hindi song' in result.summary


def test_playlist_recommendation_uses_last_selected_identity_and_waits():
    agent, _, calls=fixture_agent(playlists=[{'id':'mine','name':'Classics','uri':'spotify:playlist:mine'}])
    played=agent.answer('play my Classics playlist')
    context=agent.thread_context(played,{})
    calls.clear()
    assert agent.can_handle_with_context('recommend me',context)
    response=agent.answer_with_context('recommend me',context)
    assert response.action_request['payload']['uri']=='spotify:playlist:mine'
    assert 'Classics' in response.summary and not calls
    accepted=agent.execute_action_request(response.action_request)
    assert accepted.status=='answered'
    assert calls==[('spotify_playback',{'action':'play','context_uri':'spotify:playlist:mine'})]
    accepted_context=agent.thread_context(accepted,agent.thread_context(response,context))
    assert accepted_context['last_playlist']['source_uri']=='spotify:playlist:mine'
    assert not accepted_context['playlist_suggestion']


def test_daily_mix_suggestion_is_saved_identity_not_global_search():
    agent, _, calls=fixture_agent(playlists=[{'id':'mix2','name':'Daily Mix 2','uri':'spotify:playlist:mix2'}])
    response=agent.answer('recommend my daily mix 2')
    assert response.action_request['payload']['uri']=='spotify:playlist:mix2'
    assert not any(name=='spotify_search' or args.get('action')=='play' for name,args in calls)


def test_missing_daily_mix_suggestion_cannot_play_arbitrary_song():
    agent, _, calls=fixture_agent(playlists=[])
    result=agent.answer('suggest my daily mix 1')
    assert result.status=='needs_fetch' and 'Spotify link' in result.summary
    assert not result.action_request
    assert all(name=='spotify_playlists' for name,_ in calls)
    context=agent.thread_context(result,{})
    calls.clear()
    linked=agent.answer_with_context('https://open.spotify.com/playlist/privateMix',context)
    assert linked.action_request['payload']['uri']=='spotify:playlist:privateMix'
    assert not calls  # Providing a link still waits for acceptance.


@pytest.mark.parametrize('text',['reduce the volume to 10%','increase the volume','what si playing?'])
def test_exact_live_volume_and_current_wording_has_a_direct_plan(text):
    agent,_,_=fixture_agent(planner=lambda *_:pytest.fail('No model round trip for a direct control'))
    assert agent.can_handle(text)
    assert agent._fast_plan(text).operation in {'set_volume','adjust_volume','current'}


def test_exact_playlist_count_typo_reads_all_saved_playlists_without_model():
    agent,_,calls=fixture_agent(playlists=[{'id':'one','name':'First'},{'id':'two','name':'🔥'}],
        planner=lambda *_:pytest.fail('Playlist inventory must be a live read'))
    assert agent.can_handle('how many playlsit do i have?')
    result=agent.answer('how many playlsit do i have?')
    assert result.status=='answered' and '2' in result.summary
    assert all(name=='spotify_playlists' and args['action']=='list' for name,args in calls)


def test_exact_emoji_typo_and_followup_show_own_choices():
    playlists=[{'id':'one','name':'🔥','uri':'spotify:playlist:one'},{'id':'two','name':'♨︎','uri':'spotify:playlist:two'}]
    agent,_,calls=fixture_agent(playlists=playlists,planner=lambda *_:pytest.fail('No model for a playlist source'))
    response=agent.answer('play something from emoji playlis')
    assert response.status=='needs_fetch' and len(response.structured_payload['choices'])==2
    followup=agent.answer_with_context('what about my emoji playlist',agent.thread_context(response,{}))
    assert len(followup.structured_payload['choices'])==2
    assert not any(name=='spotify_search' or args.get('action')=='play' for name,args in calls)


def test_go_back_same_amount_reverses_previous_seek_without_model():
    import time
    agent,registry,_=fixture_agent(planner=lambda *_:pytest.fail('Seek follow-up must preserve the exact distance'))
    position=[90000]; calls=[]
    def invoke(name,args,**kwargs):
        calls.append(args)
        if args['action']=='seek':position[0]=args['position_ms']
        return {'ok':True,'data':{'track':{'name':'Song','uri':'spotify:track:one'},'progress_ms':position[0],
            'duration_ms':180000,'is_playing':False,'device':{'id':'vellum'}}}
    registry.invoke=invoke
    context={'at':time.time(),'last_seek_delta_ms':45000,'last_plan':MusicPlan(operation='seek',seek_delta_ms=45000).model_dump()}
    assert agent.can_handle_with_context('go back the same amount',context)
    result=agent.answer_with_context('go back the same amount',context)
    assert result.status=='answered' and 'Moved back 45 seconds' in result.summary
    assert [args['position_ms'] for args in calls if args['action']=='seek']==[45000]
    reverse_context=agent.thread_context(result,context)
    assert reverse_context['last_seek_delta_ms']==-45000
    forward=agent.answer_with_context('go forward the same amount',reverse_context)
    assert forward.status=='answered' and position[0]==90000


def test_seek_context_is_captured_from_execution_and_failed_seek_does_not_replace_it():
    from agent.agents.base import SpecialistResponse
    from agent.agents.music import MusicAgent
    success=SpecialistResponse(agent='MusicAgent',status='answered',summary='Moved forward 45 seconds',
        structured_payload={'music_plan':MusicPlan(operation='seek',seek_delta_ms=45000).model_dump()})
    context=MusicAgent.thread_context(success,{})
    assert context['last_seek_delta_ms']==45000
    failure=SpecialistResponse(agent='MusicAgent',status='error',summary='Seek failed',
        structured_payload={'music_plan':MusicPlan(operation='seek',seek_delta_ms=-10000).model_dump()})
    assert MusicAgent.thread_context(failure,context)['last_seek_delta_ms']==45000


def test_saved_playlist_inventory_paginates_and_refuses_an_incomplete_count():
    pages=iter([{'items':[{'id':'a','name':'First'}],'next':'page2'},
                {'items':[{'id':'b','name':'Second'}],'next':None}])
    offsets=[]
    def invoke(_,args):
        offsets.append(args['offset'])
        return next(pages)
    assert len(SpotifyCapabilityService.saved_playlists(invoke))==2
    assert offsets==[0,50]
    with pytest.raises(ValueError,match='full saved list is not verified'):
        SpotifyCapabilityService.saved_playlists(lambda *_:{'items':[{'id':'a'}],'next':'repeated'})


def test_exact_bollywood_typo_selects_only_saved_matching_identity():
    agent,_,calls=fixture_agent(playlists=[{'id':'mine','name':'Nostalgic Bollywood Songs (2000 -2010)','uri':'spotify:playlist:mine'}],
        planner=lambda *_:pytest.fail('No model round trip for a playlist'))
    response=agent.answer('can u play from the bolloywood playlist')
    assert response.status=='answered'
    assert any(args.get('context_uri')=='spotify:playlist:mine' for _,args in calls)
    assert not any(name=='spotify_search' for name,_ in calls)


def test_same_seek_without_recent_distance_asks_without_model_or_write():
    agent,_,calls=fixture_agent(planner=lambda *_:pytest.fail('Do not guess a seek distance'))
    assert agent.can_handle('go back the same amount')
    result=agent.answer('go back the same amount')
    assert result.status=='needs_fetch' and 'How many seconds' in result.summary and not calls


def test_exact_emoji_choice_wins_over_a_longer_name_containing_that_emoji():
    agent,_,calls=fixture_agent(playlists=[{'id':'fire','name':'🔥','uri':'spotify:playlist:fire'},
        {'id':'heart','name':'🔪❤️‍🔥','uri':'spotify:playlist:heart'}],planner=lambda *_:pytest.fail('No model for an offered choice'))
    response=agent.answer('what about my emoji playlist')
    context=agent.thread_context(response,{})
    assert agent.can_handle_with_context('🔥',context)
    calls.clear()
    selected=agent.answer_with_context('🔥',context)
    assert selected.status=='answered'
    assert calls==[('spotify_playback',{'action':'play','context_uri':'spotify:playlist:fire'})]


def test_shared_dispatcher_preserves_seek_distance_and_routes_playlist_inventory(tmp_path):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.state import MasterThreadStateStore
    from agent.profiles import AgentCatalog
    agent,registry,_=fixture_agent(planner=lambda *_:pytest.fail('These requests must delegate without a model'))
    position=[45000]; volume=[38]; writes=[]
    def invoke(name,args,**kwargs):
        if name=='spotify_playlists':
            return {'ok':True,'data':{'items':[{'id':'mine','name':'🔥'}],'next':None}}
        if args['action']=='seek':
            position[0]=args['position_ms']; writes.append(position[0])
        if args['action']=='set_volume':volume[0]=args['volume_percent']
        return {'ok':True,'data':{'track':{'name':'Song','uri':'spotify:track:one'},'progress_ms':position[0],
            'duration_ms':180000,'is_playing':False,'device':{'id':'vellum','volume_percent':volume[0]}}}
    registry.invoke=invoke
    dispatcher=LiveAgentDispatcher(vault_root=tmp_path,agent_catalog=AgentCatalog(profile_dir=tmp_path/'profiles',executors={'MusicAgent':agent}),
        state_store=MasterThreadStateStore(sessions_db=tmp_path/'sessions.db'))
    assert dispatcher.maybe_handle('skip 45 secs','music').status=='answered'
    assert dispatcher.maybe_handle('what si playing?','music').status=='answered'
    result=dispatcher.maybe_handle('go back the same amount','music')
    assert result.agent_name=='MusicAgent' and 'Moved back 45 seconds' in result.answer
    assert writes==[90000,45000]
    assert not agent.can_handle_with_context('go back the same amount',{})
    result=dispatcher.maybe_handle('reduce the volume to 10%','music')
    assert result.agent_name=='MusicAgent' and '38% to 10%' in result.answer and volume[0]==10
    result=dispatcher.maybe_handle('how many playlsit do i have?','music')
    assert result.agent_name=='MusicAgent' and '1 saved playlists' in result.answer
