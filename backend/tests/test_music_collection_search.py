"""Regressions from the user's mixed confirmation and music search chat."""
import time

import pytest

from agent.agents.music import MusicAgent
from agent.contracts.music import MusicPlan, MusicChoiceRequired
from agent.tools.capabilities.spotify_service import SpotifyCapabilityService
from test_music_agent import fixture_agent


@pytest.mark.parametrize('text', ['add it to my liked playlist', 'remove it from my liked playlist'])
def test_liked_playlist_alias_is_library_not_named_playlist(text):
    plan = MusicAgent._fast_plan(text)
    assert plan.collection == 'liked' and plan.query == ''


@pytest.mark.parametrize('action', ['save', 'remove'])
def test_clear_membership_request_executes_and_verifies_without_extra_confirmation(action):
    agent, registry, _ = fixture_agent()
    saved = action == 'remove'
    writes = []
    def invoke(name, args, **kwargs):
        nonlocal saved
        if args['action'] == 'get_state':
            return {'ok': True, 'data': {'track': {'name': 'Song', 'uri': 'spotify:track:one'}}}
        if args['action'] == 'contains':
            return {'ok': True, 'data': {'items': [saved]}}
        writes.append(args)
        saved = args['action'] == 'save'
        return {'ok': True, 'data': {}}
    registry.invoke = invoke
    response = agent.answer('add it to my liked songs' if action == 'save' else 'remove it from my liked songs')
    assert response.status == 'answered'
    assert not response.action_request
    assert len(writes) == 1 and writes[0]['confirm'] is True
    assert saved == (action == 'save')


@pytest.mark.parametrize('text', ['remove the untile i found from my liked songs', 'no remove the song called until i found y from my liked songs'])
def test_named_removal_cleans_command_words(text):
    agent = fixture_agent()[0]
    assert agent.can_handle(text)
    plan = agent._fast_plan(text)
    assert plan.operation == 'remove_current'
    assert not plan.track_query.startswith(('the ', 'song ', 'called '))


def test_remove_followup_keeps_destination_from_prior_request():
    agent = fixture_agent()[0]
    context = {'at': time.time(), 'last_plan': MusicPlan(operation='remove_current', collection='playlist', query='Classics').model_dump()}
    response = agent.answer_with_context('remove the song untile i found u', context)
    assert response.structured_payload['music_plan']['operation'] == 'remove_current'
    assert response.structured_payload['music_plan']['query'] == 'Classics'
    assert response.structured_payload['music_plan']['track_query'] == 'untile i found u'


def test_typo_removal_resolves_within_actual_collection_not_public_search():
    calls = []
    track = {'name': 'Until I Found You', 'uri': 'spotify:track:real', 'artists': [{'name': 'Stephen Sanchez'}]}
    def invoke(name, args):
        calls.append((name, args))
        assert name == 'spotify_library'
        return {'items': [{'track': track}], 'next': None} if args['action'] == 'list' else {'items': [True]}
    proposal = SpotifyCapabilityService().prepare_collection_change(
        MusicPlan(operation='remove_current', track_query='untile i found u'), invoke)
    assert proposal.track_uri == 'spotify:track:real'
    assert calls[0][1]['action'] == 'list'


def test_ambiguous_collection_titles_never_choose_first():
    tracks = [{'name': 'Until I Found You', 'uri': 'spotify:track:' + str(i), 'artists': [{'name': artist}]}
              for i, artist in enumerate(['Stephen Sanchez', 'Cover Artist'])]
    def invoke(name, args):
        assert args['action'] == 'list'
        return {'items': [{'track': t} for t in tracks], 'next': None}
    with pytest.raises(MusicChoiceRequired):
        SpotifyCapabilityService().prepare_collection_change(MusicPlan(operation='remove_current', track_query='until i found you'), invoke)


@pytest.mark.parametrize('query', ['play the latest drake album', "play drake's latest album", 'play the newest album by drake'])
def test_latest_artist_album_is_typed_not_song(query):
    plan = MusicAgent._fast_plan(query)
    assert plan.operation == 'play_album' and plan.latest is True and plan.artist == 'drake'


@pytest.mark.parametrize('query,artist', [('latest album from j cole','j cole'), ('latest album from lil baby','lil baby'), ('can u play j cole latest album','j cole'), ('latest album from The Game','The Game')])
def test_latest_chat_album_shorthand_never_waits_for_a_model(query,artist):
    agent=fixture_agent(planner=lambda *_:pytest.fail('Album wording must not wait for the model'))[0]
    assert agent.can_handle(query)
    plan=agent._fast_plan(query)
    assert plan.operation=='play_album' and plan.latest and plan.artist==artist


def test_playlist_count_latest_chat_typo_reads_library_without_model():
    agent,_,calls=fixture_agent(planner=lambda *_:pytest.fail('A playlist count must read Spotify'))
    assert agent.can_handle('how many playlist is have?')
    result=agent.answer('how many playlist is have?')
    assert result.status=='answered' and '1 saved playlist' in result.summary
    assert any(name=='spotify_playlists' for name,_ in calls)


@pytest.mark.parametrize('requested,catalog', [('j cole','J. Cole'), ('r e m','R.E.M.'), ('宇多田ヒカル','宇多田ヒカル')])
def test_latest_album_matches_artist_punctuation_and_non_latin_names(requested,catalog):
    def invoke(name,args):
        if name=='spotify_search':
            return {'artists':{'items':[{'name':catalog,'id':'artist'}]}}
        assert name=='spotify_albums'
        return {'items':[{'name':'Latest','uri':'spotify:album:latest','album_type':'album','release_date':'2026-01-01','artists':[{'id':'artist','name':catalog}]}],'next':None}
    album=SpotifyCapabilityService().resolve_album(MusicPlan(operation='play_album',latest=True,artist=requested),invoke)
    assert album['uri']=='spotify:album:latest'


def test_named_album_artist_punctuation_uses_verified_credits():
    def invoke(name,args):
        assert name=='spotify_search' and args['types']==['album']
        return {'albums':{'items':[{'name':'The Off-Season','uri':'spotify:album:cole','artists':[{'name':'J. Cole'}]}]}}
    album=SpotifyCapabilityService().resolve_album(MusicPlan(operation='play_album',query='The Off-Season',artist='j cole'),invoke)
    assert album['uri']=='spotify:album:cole'


def test_artist_punctuation_collision_requires_choice_before_album_playback():
    def invoke(name,args):
        if name=='spotify_search': return {'artists':{'items':[{'id':'a','name':'A.B.C.'},{'id':'b','name':'A B C.'}]}}
        if name=='music_kworb': return {}
        pytest.fail('An ambiguous artist must not fetch or play albums')
    with pytest.raises(MusicChoiceRequired):
        SpotifyCapabilityService().resolve_album(MusicPlan(operation='play_album',latest=True,artist='a b c'),invoke)


def test_latest_album_uses_artist_catalog_dates_not_search_ranking():
    calls = []
    def invoke(name, args):
        calls.append((name, args))
        if name == 'spotify_search':
            assert args['types'] == ['artist']
            return {'artists': {'items': [{'name': 'Drake', 'id': 'drake'}]}}
        if name == 'spotify_albums':
            return {'items': [
                {'name': 'Old', 'id': 'old', 'uri': 'spotify:album:old', 'album_type': 'album', 'release_date': '2020-01-01', 'artists': [{'id': 'drake'}]},
                {'name': 'Latest', 'id': 'new', 'uri': 'spotify:album:new', 'album_type': 'album', 'release_date': '2026-01-01', 'artists': [{'id': 'drake'}]},
                {'name': 'Single', 'uri': 'spotify:album:single', 'album_type': 'single', 'release_date': '2026-09-01', 'artists': [{'id': 'drake'}]}], 'next': None}
        if args['action'] == 'get_currently_playing':
            return {'is_playing': True, 'context': {'uri': 'spotify:album:new'}}
        return {}
    summary = SpotifyCapabilityService().execute(MusicPlan(operation='play_album', artist='Drake', latest=True), invoke)
    assert 'Latest' in summary
    assert sum(args.get('action') == 'play' for _, args in calls) == 1
    assert next(args for _, args in calls if args.get('action') == 'play')['context_uri'] == 'spotify:album:new'


def mixed_dispatcher(tmp_path, release=None):
    from agent.agents.base import SpecialistResponse
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.runtime import DelegationRuntime
    from agent.master.state import MasterThreadStateStore
    from agent.profiles import AgentCatalog
    calls = []
    class Music:
        def can_handle(self, message): return message == 'what is playing'
        def answer(self, message):
            return SpecialistResponse(agent='MusicAgent',status='answered',summary='Current song.')
        def execute_action_request(self, action):
            calls.append(('music', action['payload']))
            return SpecialistResponse(agent='MusicAgent', status='answered', summary='Removed the song.')
    class Sports:
        def can_handle(self, message): return 'nba' in message.lower()
        def answer(self, message):
            calls.append(('sports', message))
            if release is not None:
                assert release.wait(3)
            return SpecialistResponse(agent='SportsAgent', status='answered', summary='NBA update.')
    state = MasterThreadStateStore(sessions_db=tmp_path/'sessions.db')
    state.set_pending_action('chat', {'agent': 'MusicAgent', 'action': 'music.change_collection', 'payload': {'target': 'exact'}})
    catalog = AgentCatalog(profile_dir=tmp_path/'profiles', executors={'MusicAgent': Music(), 'SportsAgent': Sports()})
    runtime = DelegationRuntime(agent_catalog=catalog, memory_orchestrator=None, audit_path=tmp_path/'audit.jsonl', pending_action_store=state)
    dispatcher = LiveAgentDispatcher(vault_root=tmp_path, agent_catalog=catalog, state_store=state, delegation_runtime=runtime)
    return dispatcher, calls, state


def test_mixed_yes_claims_only_pending_action_and_routes_nba_separately(tmp_path):
    dispatcher, calls, state = mixed_dispatcher(tmp_path)
    result = dispatcher.maybe_handle('what is happening in the nba and yes', 'chat')
    assert result and 'Removed the song.' in result.answer and 'NBA update.' in result.answer
    assert ('sports', 'what is happening in the nba') in calls
    assert ('music', {'target': 'exact'}) in calls
    assert state.get_pending_action('chat') is None


def test_confirmation_finishes_before_slow_read_and_never_confirms_queue(tmp_path):
    import threading
    release = threading.Event()
    dispatcher, calls, state = mixed_dispatcher(tmp_path, release)
    pending = state.get_pending_action('chat')
    state.set_pending_action('chat', {**pending, 'batch_id':'old', 'queued_actions':[
        {**pending, 'payload':{'target':'next'}, 'preview':'Another song'}]})
    emitted = []
    def emit(part):
        emitted.append(part)
        if part.agent_name == 'MusicAgent':
            assert not release.is_set()
            release.set()
    result = dispatcher.maybe_handle('yes and what is happening in the nba', 'chat', on_result=emit)
    assert [p.agent_name for p in emitted] == ['MusicAgent', 'SportsAgent']
    assert 'NBA update.' in result.answer
    assert state.get_pending_action('chat')['payload'] == {'target':'next'}
    assert sum(c[0] == 'music' for c in calls) == 1


@pytest.mark.parametrize('message', ['what does yes mean in nba', 'what is happening in the nba and "yes"', 'yes and yes and what is happening in the nba'])
def test_incidental_quoted_or_repeated_yes_does_not_authorize(tmp_path, message):
    dispatcher, calls, state = mixed_dispatcher(tmp_path)
    dispatcher.maybe_handle(message, 'chat')
    assert not any(c[0] == 'music' for c in calls)
    assert state.get_pending_action('chat') is not None


@pytest.mark.parametrize('action', ['save', 'remove'])
def test_playlist_edit_direct_once_with_stable_song_and_verified_membership(action):
    agent, registry, _ = fixture_agent()
    songs = {'spotify:track:one'} if action == 'remove' else set()
    writes = []
    def invoke(name, args, **kwargs):
        if args['action'] == 'get_state':
            return {'ok':True, 'data':{'track':{'name':'Song', 'uri':'spotify:track:one'}}}
        if args['action'] == 'list':
            data = {'items':[{'id':'mine', 'name':'Classics', 'uri':'spotify:playlist:mine'}], 'next':None}
        elif args['action'] == 'tracks':
            data = {'items':[{'item':{'uri':uri}} for uri in songs], 'next':None}
        else:
            writes.append(args)
            if args['action'] == 'add_items': songs.update(args['uris'])
            else: songs.difference_update(args['uris'])
            data = {}
        return {'ok':True, 'data':data}
    registry.invoke = invoke
    response = agent.answer(('add it to' if action == 'save' else 'remove it from') + ' my Classics playlist')
    assert response.status == 'answered' and not response.action_request
    assert len(writes) == 1 and writes[0]['uris'] == ['spotify:track:one']
    assert ('spotify:track:one' in songs) == (action == 'save')


def test_ambiguous_saved_track_choice_preserves_playlist_and_removal():
    agent, registry, _ = fixture_agent()
    tracks = [{'name':'Song', 'uri':'spotify:track:'+str(i), 'artists':[{'name':name}]} for i,name in enumerate(['One','Two'])]
    songs = {t['uri'] for t in tracks}
    writes = []
    def invoke(name, args, **kwargs):
        if args['action'] == 'list':
            data = {'items':[{'id':'mine','name':'Classics','uri':'spotify:playlist:mine'}], 'next':None}
        elif args['action'] == 'tracks':
            data = {'items':[{'item':t} for t in tracks if t['uri'] in songs], 'next':None}
        else:
            assert args['action'] == 'remove_items'
            writes.append(args)
            songs.difference_update(args['uris'])
            data = {}
        return {'ok':True,'data':data}
    registry.invoke = invoke
    first = agent.answer('remove the song Song from my Classics playlist')
    assert first.status == 'needs_fetch' and not first.action_request and writes == []
    context = agent.thread_context(first,{})
    response = agent.answer_with_context('2',context)
    assert response.status == 'answered'
    assert songs == {'spotify:track:0'} and writes[0]['playlist_id'] == 'mine'


def test_typo_catalog_search_broadens_once_then_selects_strong_match():
    calls = []
    def invoke(name, args):
        calls.append(args)
        if args['query'].startswith('track:'): return {'tracks':{'items':[]}}
        return {'tracks':{'items':[{'name':'Until I Found You','uri':'spotify:track:one','artists':[{'name':'Stephen Sanchez'}]}]}}
    track = SpotifyCapabilityService().resolve_song(MusicPlan(operation='play_song',query='untile i found u',artist='Stephen Sanchez'), invoke)
    assert track['uri'] == 'spotify:track:one' and len(calls) == 2


def test_album_connector_exposes_exact_paginated_artist_endpoint():
    import json
    from plugins.connectors.spotify.tools import spotify_albums
    from test_spotify_tools import FakeService
    service = FakeService()
    result = json.loads(spotify_albums({'action':'artist_albums','artist_id':'drake','include_groups':'album','limit':50,'offset':50}, service=service))
    assert result['ok'] is True
    assert service.calls == [('GET','/artists/drake/albums',{'params':{'include_groups':'album','limit':10,'offset':50}})]
    service.calls.clear()
    assert json.loads(spotify_albums({'action':'artist_albums','artist_id':'../../me'},service=service))['ok'] is False
    assert service.calls == []


def test_album_play_does_not_claim_success_from_only_write_receipt(monkeypatch):
    monkeypatch.setattr('agent.tools.capabilities.spotify_service.time.sleep',lambda _:None)
    service = SpotifyCapabilityService()
    monkeypatch.setattr(service,'resolve_album',lambda *_:{'name':'Album','uri':'spotify:album:wanted'})
    calls = []
    def invoke(name,args):
        calls.append(args)
        return {'is_playing':True,'context':{'uri':'spotify:album:wrong'}}
    with pytest.raises(ValueError,match='did not confirm'):
        service.execute(MusicPlan(operation='play_album',query='Album'),invoke)
    assert sum(c['action']=='play' for c in calls) == 1


def test_current_song_edit_and_nba_read_are_independent_and_stream_immediately(tmp_path):
    import threading
    release = threading.Event()
    dispatcher, _, state = mixed_dispatcher(tmp_path, release)
    state.clear_pending_action('chat')
    agent, registry, _ = fixture_agent()
    saved = [False]
    def invoke(name,args,**kwargs):
        if args['action'] == 'get_state': data = {'track':{'name':'Song','uri':'spotify:track:one'}}
        elif args['action'] == 'contains': data = {'items':saved[:]}
        else:
            assert args['action']=='save' and args['confirm'] is True
            saved[0]=True
            data={}
        return {'ok':True,'data':data}
    registry.invoke = invoke
    dispatcher.agent_catalog.register_executor('MusicAgent',agent)
    emitted = []
    def emit(part):
        emitted.append(part.agent_name)
        if part.agent_name == 'MusicAgent': release.set()
    result = dispatcher.maybe_handle('add it to my liked playlist and what is happening in the nba','chat',on_result=emit)
    assert result.status=='answered' and emitted==['MusicAgent','SportsAgent']
    assert saved==[True] and state.get_pending_action('chat') is None


def test_saved_song_lookup_does_not_write_when_pagination_is_incomplete(monkeypatch):
    service = SpotifyCapabilityService()
    monkeypatch.setattr('agent.tools.capabilities.spotify_service.time.monotonic',iter([0,1,13]).__next__)
    def invoke(name,args):
        assert args['action']=='list'
        return {'items':[{'track':{'name':'Song','uri':'spotify:track:one'}}],'next':'more'}
    with pytest.raises(ValueError,match='time limit'):
        service.prepare_collection_change(MusicPlan(operation='remove_current',track_query='Song'),invoke)


def test_saved_version_choice_accepts_distinct_artist_without_losing_target():
    choices=[{'title':'Song','artist':'First Artist','uri':'spotify:track:first','kind':'track'},
             {'title':'Song','artist':'Second Artist','uri':'spotify:track:second','kind':'track'}]
    selected=MusicAgent._source_choice('by Second Artist',{'choices':choices})
    assert selected['uri']=='spotify:track:second'


def test_mixed_confirm_and_same_owner_read_advance_queue_only_once(tmp_path):
    dispatcher, calls, state = mixed_dispatcher(tmp_path)
    pending=state.get_pending_action('chat')
    state.set_pending_action('chat',{**pending,'queued_actions':[{**pending,'payload':{'target':'next'},'preview':'Another song'}]})
    result=dispatcher.maybe_handle('yes and what is playing and what is happening in the nba','chat')
    assert 'Current song.' in result.answer and result.answer.count('Next change awaiting confirmation:')==1
    assert state.get_pending_action('chat')['payload']=={'target':'next'}
    assert sum(c[0]=='music' for c in calls)==1


def test_model_cannot_invent_a_resolved_song_uri():
    agent, registry, calls=fixture_agent(planner=lambda *_:{'operation':'save_current','track_query':'No match','track_uri':'spotify:track:invented'})
    response=agent.answer('put a particular song in my library')
    assert response.status=='needs_fetch'
    assert not any(args.get('action') in {'save','remove','add_items','remove_items'} for _,args in calls)


def test_album_and_collection_intent_normalize_user_whitespace():
    assert MusicAgent._fast_plan('play ' + ' '*10000 + "drake's latest album").operation=='play_album'
    assert MusicAgent._fast_plan('remove\n it from my\tliked playlist').collection=='liked'


def test_new_direct_music_edit_retires_old_preview_but_preserves_other_queued_actions(tmp_path):
    dispatcher, _, state = mixed_dispatcher(tmp_path)
    pending=state.get_pending_action('chat')
    state.set_pending_action('chat',{**pending,'queued_actions':[
        {'agent':'XAgent','action':'x.publish_post','payload':{'text':'A reviewed draft'},'preview':'Publish the reviewed draft?'}]})
    agent, registry, _ = fixture_agent()
    saved=[False]
    def invoke(name,args,**kwargs):
        if args['action']=='get_state': data={'track':{'name':'Song','uri':'spotify:track:one'}}
        elif args['action']=='contains': data={'items':saved[:]}
        else: saved[0]=True; data={}
        return {'ok':True,'data':data}
    registry.invoke=invoke
    dispatcher.agent_catalog.register_executor('MusicAgent',agent)
    result=dispatcher.maybe_handle('add it to my liked playlist','chat')
    assert 'Added Song' in result.answer and saved==[True]
    assert state.get_pending_action('chat')['agent']=='XAgent'
    assert 'reviewed draft' in result.answer
