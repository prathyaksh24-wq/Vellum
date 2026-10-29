"""Combined typed music requests keep exact playback and library targets."""
import pytest

from dataclasses import replace

from agent.agents.live_dispatcher import LiveAgentDispatcher
from agent.master.state import MasterThreadStateStore
from agent.profiles import AgentCatalog
from agent.tools.capabilities.kworb_service import KworbCapabilityService
from test_kworb_music import CHART, INDEX
from test_music_agent import fixture_agent


def compound_dispatcher(tmp_path, *, fail_action='', tracks=None):
    agent, registry, _ = fixture_agent(tracks=tracks, planner=lambda *_: pytest.fail("Do not turn combined actions into a song title"))
    reader = KworbCapabilityService(fetch=lambda url: (
        INDEX + '<table><tr><td>Spain</td><td><a href="country/es_daily.html">Daily</a></td></tr></table>'
        if url.endswith('/spotify/') else CHART.replace('India', 'Spain')))
    registry.register(reader.build_registry().get('music_kworb'))
    calls, saved = [], set()
    current = {'uri': 'spotify:track:before', 'name': 'Before Song', 'artists': [{'name': 'Before Artist'}]}
    device = {'id': 'vellum', 'volume_percent': 50, 'supports_volume': True}
    settings = {'shuffle': False, 'repeat': 'off', 'progress_ms': 45000, 'context': None}
    original_invoke = registry.invoke

    def invoke(name, args, **kwargs):
        calls.append((name, dict(args)))
        if name == 'spotify_playback':
            if args['action'] == fail_action:
                return {'ok': False, 'error': {'message': 'Device unavailable'}}
            if args['action'] == 'play' and args.get('uris'):
                current.update(uri=args['uris'][0], name='First Song', artists=[{'name': 'First Artist'}])
                settings['context'] = None
            if args['action'] == 'play' and args.get('context_uri'):
                settings['context'] = {'uri': args['context_uri']}
                current.update(uri='spotify:track:playlist',name='Playlist Song',artists=[{'name':'Playlist Artist'}])
            if args['action'] == 'next': current.update(uri='spotify:track:next', name='Next Song')
            if args['action'] == 'set_volume': device['volume_percent'] = args['volume_percent']
            if args['action'] == 'set_shuffle': settings['shuffle'] = args['shuffle']
            if args['action'] == 'set_repeat': settings['repeat'] = args['state']
            if args['action'] == 'seek': settings['progress_ms'] = args['position_ms']
            return {'ok': True, 'data': {'track': dict(current), 'is_playing': True, 'device': dict(device), **settings}}
        if name == 'spotify_library':
            if args['action'] == 'contains':
                return {'ok': True, 'data': {'items': [value in saved for value in args['uris']]}}
            assert args['action'] == 'save' and args['confirm'] is True
            saved.update(args['uris'])
            return {'ok': True, 'data': {}}
        return original_invoke(name, args, **kwargs)

    registry.invoke = invoke
    state = MasterThreadStateStore(sessions_db=tmp_path / 'sessions.db')
    state.set_active_agent('compound', 'YoutubeAgent', selected=True)
    dispatcher = LiveAgentDispatcher(vault_root=tmp_path,
        agent_catalog=AgentCatalog(profile_dir=tmp_path / 'profiles', executors={'MusicAgent': agent}),
        state_store=state)
    return dispatcher, calls, saved, state


def test_original_recording_is_selected_without_dropping_compound_controls(tmp_path):
    tracks = [
        {'name': 'Blinding Lights', 'uri': 'spotify:track:cover', 'artists': [{'name': 'Loi'}],
         'album': {'name': 'Blinding Lights', 'release_date': '2021-09-17'}},
        {'name': 'Blinding Lights', 'uri': 'spotify:track:original', 'artists': [{'name': 'The Weeknd'}],
         'album': {'name': 'After Hours', 'release_date': '2020-03-20'}},
    ]
    dispatcher, calls, _, _ = compound_dispatcher(tmp_path, tracks=tracks)
    result = dispatcher.maybe_handle('Play Blinding Lights, then set volume to 25% and turn on shuffle.', 'compound')
    assert result.status == 'answered', result.answer
    writes = [args for name, args in calls if name == 'spotify_playback' and args['action'] != 'get_state']
    assert writes == [{'action': 'play', 'uris': ['spotify:track:original']},
                      {'action': 'set_volume', 'volume_percent': 25, 'device_id': 'vellum'},
                      {'action': 'set_shuffle', 'shuffle': True, 'device_id': 'vellum'}]
    assert 'The Weeknd' in result.answer


def test_genuine_artist_clarification_resumes_remaining_controls_once(tmp_path):
    tracks = [{'name': 'Blinding Lights', 'uri': f'spotify:track:{key}', 'artists': [{'name': artist}]}
              for key, artist in [('original', 'The Weeknd'), ('cover', 'Loi')]]
    dispatcher, calls, _, _ = compound_dispatcher(tmp_path, tracks=tracks)
    first = dispatcher.maybe_handle('set volume to 40% then play Blinding Lights then set volume to 25% and turn on shuffle', 'compound')
    assert first.status == 'needs_fetch'
    result = dispatcher.maybe_handle('by weekend', 'compound')
    assert result.status == 'answered' and 'Shuffle is on' in result.answer, result.answer
    writes = [args for name, args in calls if name == 'spotify_playback' and args['action'] != 'get_state']
    assert writes == [{'action': 'set_volume', 'volume_percent': 40, 'device_id': 'vellum'},
                      {'action': 'play', 'uris': ['spotify:track:original']},
                      {'action': 'set_volume', 'volume_percent': 25, 'device_id': 'vellum'},
                      {'action': 'set_shuffle', 'shuffle': True, 'device_id': 'vellum'}]
    dispatcher.maybe_handle('by weekend', 'compound')
    assert sum(args.get('action') == 'set_shuffle' for _, args in calls) == 1


@pytest.mark.parametrize('interruption', ['cancel', 'set volume to 60%', 'expired', 'wrong-thread'])
def test_artist_reply_cannot_resume_cancelled_replaced_expired_or_other_thread_actions(tmp_path, interruption):
    tracks = [{'name': 'Blinding Lights', 'uri': f'spotify:track:{key}', 'artists': [{'name': artist}]}
              for key, artist in [('original', 'The Weeknd'), ('cover', 'Loi')]]
    dispatcher, calls, _, state = compound_dispatcher(tmp_path, tracks=tracks)
    dispatcher.maybe_handle('play Blinding Lights then set volume to 25% and turn on shuffle', 'compound')
    if interruption == 'expired':
        context = state.get_specialist_context('compound', 'MusicAgent')
        context['compound_continuation']['at'] -= 1801
        state.set_specialist_context('compound', 'MusicAgent', context)
    elif interruption != 'wrong-thread':
        dispatcher.maybe_handle(interruption, 'compound')
    calls.clear()
    dispatcher.maybe_handle('by weekend', 'other' if interruption == 'wrong-thread' else 'compound')
    assert not any(args.get('action') in {'set_volume', 'set_shuffle'} for _, args in calls)


def test_unclear_reply_keeps_original_deadline_and_error_clears_remaining_actions(tmp_path):
    tracks = [{'name': 'Blinding Lights', 'uri': f'spotify:track:{key}', 'artists': [{'name': artist}]}
              for key, artist in [('original', 'The Weeknd'), ('cover', 'Loi')]]
    dispatcher, calls, _, state = compound_dispatcher(tmp_path, tracks=tracks, fail_action='play')
    dispatcher.maybe_handle('play Blinding Lights then set volume to 25% and turn on shuffle', 'compound')
    original_at = state.get_specialist_context('compound', 'MusicAgent')['compound_continuation']['at']
    unclear = dispatcher.maybe_handle('yes', 'compound')
    assert unclear.status == 'needs_fetch'
    assert state.get_specialist_context('compound', 'MusicAgent')['compound_continuation']['at'] == original_at
    failed = dispatcher.maybe_handle('by weekend', 'compound')
    assert failed.status == 'error' and 'Not run' in failed.answer
    assert not state.get_specialist_context('compound', 'MusicAgent').get('compound_continuation')
    assert not any(args.get('action') in {'set_volume', 'set_shuffle'} for _, args in calls)


def test_artist_selection_preserves_captured_and_reference_to_request_start_song(tmp_path):
    tracks = [{'name': 'Blinding Lights', 'uri': f'spotify:track:{key}', 'artists': [{'name': artist}]}
              for key, artist in [('original', 'The Weeknd'), ('cover', 'Loi')]]
    dispatcher, calls, saved, _ = compound_dispatcher(tmp_path, tracks=tracks)
    dispatcher.maybe_handle('play Blinding Lights and like this song', 'compound')
    result = dispatcher.maybe_handle('by weekend', 'compound')
    assert result.status == 'answered' and saved == {'spotify:track:before'}
    assert sum(args.get('action') == 'save' for _, args in calls) == 1


def test_latest_chat_artist_correction_survives_trailing_volume_and_shuffle(tmp_path):
    tracks = [{'name':'One Right Now', 'uri':'spotify:track:'+key,'artists':[{'name':artist}]} for key,artist in
              [('original','Post Malone'),('other','David Shannon')]]
    dispatcher, calls, _, state = compound_dispatcher(tmp_path, tracks=tracks)
    dispatcher.maybe_handle('Play One Right Now by David Shannon, then set volume to 25% and turn on shuffle.', 'compound')
    result = dispatcher.maybe_handle('no from psot malone', 'compound')
    assert result is not None and result.status == 'answered' and 'Post Malone' in result.answer
    assert [args['uris'] for _,args in calls if args.get('action')=='play'] == [['spotify:track:other'],['spotify:track:original']]
    assert state.get('compound').active_agent == 'YoutubeAgent'


def test_artist_followup_survives_hours_of_active_controls_and_context_reload(tmp_path, monkeypatch):
    import time
    clock=[time.time()]
    monkeypatch.setattr('agent.agents.music.time.time',lambda:clock[0])
    tracks=[{'name':'One Right Now','uri':'spotify:track:'+key,'artists':[{'name':artist}]}
            for key,artist in [('original','Post Malone'),('other','David Shannon')]]
    dispatcher,calls,_,state=compound_dispatcher(tmp_path,tracks=tracks)
    dispatcher.maybe_handle('play One Right Now by David Shannon then set volume to 25% and turn on shuffle','compound')
    for _ in range(24):
        clock[0]+=1200
        result=dispatcher.maybe_handle('what is playing and how many playlist i have saved?','compound')
        assert result.status=='answered' and '1 saved playlist' in result.answer
    reloaded=LiveAgentDispatcher(vault_root=tmp_path,agent_catalog=dispatcher.agent_catalog,
        state_store=MasterThreadStateStore(sessions_db=tmp_path/'sessions.db'))
    result=reloaded.maybe_handle('no from psot malone','compound')
    assert result.status=='answered' and 'Post Malone' in result.answer
    assert [args['uris'] for _,args in calls if args.get('action')=='play']==[['spotify:track:other'],['spotify:track:original']]
    context=state.get_specialist_context('compound','MusicAgent')
    assert len(context)<25 and not context.get('compound_continuation')


def test_random_saved_playlist_compound_verifies_context_before_other_controls(tmp_path):
    dispatcher,calls,_,state=compound_dispatcher(tmp_path)
    result=dispatcher.maybe_handle('play a random song from any of my saved playlist then set volume to 25% and turn on shuffle','compound')
    assert result.status=='answered',result.answer
    assert len([args for _,args in calls if args.get('action')=='play'])==1
    assert state.get_specialist_context('compound','MusicAgent')['last_playlist']['source_uri']=='spotify:playlist:hindi'
    assert not any(name=='spotify_search' for name,_ in calls)


def test_album_correction_resumes_compound_album_and_controls(tmp_path):
    dispatcher,calls,_,_=compound_dispatcher(tmp_path)
    registry=dispatcher.agent_catalog.resolve('MusicAgent').executor.tool_registry
    original=registry.invoke
    def invoke(name,args,**kwargs):
        if name=='spotify_search' and args.get('types')==['album']:
            return {'ok':True,'data':{'albums':{'items':[
                {'name':'Her Loss','uri':'spotify:album:other','artists':[{'name':'Other Artist'}]},
                {'name':'Her Loss','uri':'spotify:album:drake','artists':[{'name':'Drake'},{'name':'21 Savage'}]},
            ]}}}
        return original(name,args,**kwargs)
    registry.invoke=invoke
    first=dispatcher.maybe_handle('play Her Loss album then set volume to 25% and turn on shuffle','compound')
    assert first.status=='needs_fetch'
    result=dispatcher.maybe_handle('no the album by Drake','compound')
    assert result.status=='answered' and 'Drake, 21 Savage' in result.answer and 'Shuffle is on' in result.answer
    assert [args['action'] for name,args in calls if name=='spotify_playback' and args['action'] not in {'get_state','get_currently_playing'}]==['play','set_volume','set_shuffle']


@pytest.mark.parametrize('message', [
    'play it and like this song that is playing',
    'like this song and play the spain sogns',
])
def test_saved_chat_combines_chart_playback_and_liking_the_song_current_at_request_start(tmp_path, message):
    dispatcher, calls, saved, state = compound_dispatcher(tmp_path)
    listed = dispatcher.maybe_handle('what are the top 20 songs in spain', 'compound')
    assert listed.status == 'answered' and 'First Song' in listed.answer
    calls.clear()
    result = dispatcher.maybe_handle(message, 'compound')
    assert result is not None and result.status == 'answered', getattr(result, 'answer', None)
    assert saved == {'spotify:track:before'}
    plays = [args for name, args in calls if name == 'spotify_playback' and args['action'] == 'play']
    assert plays == [{'action': 'play', 'uris': ['spotify:track:first', 'spotify:track:second']}]
    assert sum(name == 'spotify_library' and args['action'] == 'save' for name, args in calls) == 1
    assert 'Before Song' in result.answer and 'spain' in result.answer.casefold()
    assert not any(name == 'spotify_search' for name, _ in calls)
    assert state.get('compound').active_agent == 'YoutubeAgent'


def test_then_likes_the_new_song_after_verified_chart_playback(tmp_path):
    dispatcher, calls, saved, _ = compound_dispatcher(tmp_path)
    dispatcher.maybe_handle('top 20 songs in spain', 'compound')
    result = dispatcher.maybe_handle('play it then like this song', 'compound')
    assert result.status == 'answered', result.answer
    assert saved == {'spotify:track:first'}
    writes = [(name, args['action']) for name, args in calls if args.get('action') in {'play', 'save'}]
    assert writes == [('spotify_playback', 'play'), ('spotify_library', 'save')]


def test_music_controls_execute_in_order_with_verified_mute_restore_and_repeat_undo(tmp_path):
    dispatcher, calls, _, _ = compound_dispatcher(tmp_path)
    result = dispatcher.maybe_handle('set volume to 25% and turn on shuffle and mute then unmute and put this song on repeat then undo it', 'compound')
    assert result.status == 'answered', result.answer
    writes = [args for name, args in calls if name == 'spotify_playback' and args['action'] != 'get_state']
    assert [args['action'] for args in writes] == ['set_volume', 'set_shuffle', 'set_volume', 'set_volume', 'set_repeat', 'set_repeat']
    assert [args['volume_percent'] for args in writes if args['action'] == 'set_volume'] == [25, 0, 25]
    assert writes[-1]['state'] == 'off'
    assert 'Shuffle is on' in result.answer and 'Unmuted' in result.answer and 'Repeat is off' in result.answer


def test_failure_reports_completed_action_and_does_not_repeat_or_run_remaining_writes(tmp_path):
    dispatcher, calls, saved, _ = compound_dispatcher(tmp_path, fail_action='play')
    dispatcher.maybe_handle('top 20 songs in spain', 'compound')
    result = dispatcher.maybe_handle('like this song and play it and set volume to 25%', 'compound')
    assert result.status != 'answered'
    assert saved == {'spotify:track:before'}
    assert 'Added Before Song' in result.answer and 'Device unavailable' in result.answer and 'Not run' in result.answer
    assert sum(args.get('action') == 'play' for name, args in calls) == 1
    assert not any(args.get('action') == 'set_volume' for name, args in calls)


def test_invalid_later_action_is_checked_before_any_write(tmp_path):
    dispatcher, calls, saved, _ = compound_dispatcher(tmp_path)
    result = dispatcher.maybe_handle('like this song and set volume to 101%', 'compound')
    assert result.status == 'needs_fetch' and not saved
    assert not any(args.get('action') in {'save', 'set_volume'} for name, args in calls)


def test_chart_target_survives_a_separate_library_edit_and_volume_control(tmp_path):
    dispatcher, calls, _, _ = compound_dispatcher(tmp_path)
    dispatcher.maybe_handle('top 20 songs in spain', 'compound')
    assert dispatcher.maybe_handle('like this song', 'compound').status == 'answered'
    assert dispatcher.maybe_handle('set volume to 25%', 'compound').status == 'answered'
    result = dispatcher.maybe_handle('play the spain songs', 'compound')
    assert result.status == 'answered' and 'spain' in result.answer.casefold()
    assert [args['uris'] for name, args in calls if args.get('action') == 'play'] == [['spotify:track:first', 'spotify:track:second']]


def test_later_then_does_not_change_an_earlier_current_song_reference(tmp_path):
    dispatcher, calls, saved, _ = compound_dispatcher(tmp_path)
    dispatcher.maybe_handle('top 20 songs in spain', 'compound')
    result = dispatcher.maybe_handle('play it and like this song that is playing then set volume to 25%', 'compound')
    assert result.status == 'answered', result.answer
    assert saved == {'spotify:track:before'}
    assert [args['volume_percent'] for name, args in calls if args.get('action') == 'set_volume'] == [25]


def test_old_chart_context_remains_compatible_and_controls_cannot_extend_expiry(tmp_path):
    import time
    dispatcher, calls, _, state = compound_dispatcher(tmp_path)
    dispatcher.maybe_handle('top 20 songs in spain', 'compound')
    old = state.get_specialist_context('compound', 'MusicAgent')
    old.pop('discovery_plan'); old.pop('discovery_at')
    old['at'] = time.time() - 1700
    state.set_specialist_context('compound', 'MusicAgent', old)
    dispatcher.maybe_handle('like this song', 'compound')
    context = state.get_specialist_context('compound', 'MusicAgent')
    assert context['discovery_plan']['operation'] == 'show_chart'
    assert context['discovery_at'] == old['at']
    context['discovery_at'] -= 200
    executor = dispatcher.agent_catalog.resolve('MusicAgent').executor
    assert not executor._discovery_followup('play it', context)


def test_playlist_creation_keeps_confirmation_and_does_not_run_following_control(tmp_path):
    dispatcher, calls, _, state = compound_dispatcher(tmp_path)
    result = dispatcher.maybe_handle('create a playlist called Night with Blinding Lights by The Weeknd and set volume to 25%', 'compound')
    assert result.status == 'needs_fetch' and 'Confirm to create it' in result.answer and 'Not run' in result.answer
    assert state.get_pending_action('compound')['action'] == 'music.create_playlist'
    assert not any(args.get('action') in {'create', 'set_volume'} for name, args in calls)


def test_new_compound_library_edit_clears_an_older_pending_song_target(tmp_path):
    dispatcher, calls, saved, state = compound_dispatcher(tmp_path)
    state.set_pending_action('compound', {'agent': 'MusicAgent', 'action': 'music.change_collection',
        'payload': {'action': 'save', 'collection': 'liked', 'track_uri': 'spotify:track:stale', 'track_title': 'Stale Song'}})
    result = dispatcher.maybe_handle('like this song and set volume to 25%', 'compound')
    assert result.status == 'answered' and saved == {'spotify:track:before'}
    assert state.get_pending_action('compound') is None
    dispatcher.maybe_handle('yes', 'compound')
    assert saved == {'spotify:track:before'}
    assert sum(args.get('action') == 'save' for name, args in calls) == 1


def test_too_many_actions_do_not_write_and_missing_current_song_does_not_start_a_chart(tmp_path):
    dispatcher, calls, saved, state = compound_dispatcher(tmp_path)
    result = dispatcher.maybe_handle(' and '.join(['pause'] * 9), 'compound')
    assert result.status == 'needs_fetch' and not calls and not saved
    dispatcher.maybe_handle('top 20 songs in spain', 'compound')
    executor = dispatcher.agent_catalog.resolve('MusicAgent').executor
    original = executor.tool_registry.invoke
    executor.tool_registry.invoke = lambda name,args,**kwargs: {'ok':True,'data':{}} if name == 'spotify_playback' and args['action'] == 'get_state' else original(name,args,**kwargs)
    result = dispatcher.maybe_handle('play it and like this song', 'compound')
    assert result.status == 'error' and 'Nothing was changed' in result.answer
    assert not any(args.get('action') in {'play','save'} for name, args in calls)


def test_then_cannot_like_an_old_track_when_song_playback_has_not_been_observed(tmp_path, monkeypatch):
    dispatcher, calls, saved, _ = compound_dispatcher(tmp_path)
    registry = dispatcher.agent_catalog.resolve('MusicAgent').executor.tool_registry
    original = registry.invoke
    def stale(name, args, **kwargs):
        if name == 'spotify_playback' and args['action'] == 'get_state':
            return {'ok': True, 'data': {'track': {'uri': 'spotify:track:before', 'name': 'Before Song'}, 'is_playing': True}}
        return original(name, args, **kwargs)
    registry.invoke = stale
    monkeypatch.setattr('agent.tools.capabilities.spotify_service.time.sleep', lambda _: None)
    result = dispatcher.maybe_handle('play Blinding Lights then like this song', 'compound')
    assert result.status == 'error' and not saved
    assert 'did not confirm' in result.answer and 'Not run' in result.answer
    assert sum(args.get('action') == 'play' for name, args in calls) == 1


def test_skip_then_like_waits_for_the_new_live_track(tmp_path):
    dispatcher, calls, saved, _ = compound_dispatcher(tmp_path)
    result = dispatcher.maybe_handle('skip then like this song', 'compound')
    assert result.status == 'answered', result.answer
    assert saved == {'spotify:track:next'}
    assert sum(args.get('action') == 'next' for name, args in calls) == 1


def test_failed_public_statistic_cannot_discard_an_already_completed_music_control(tmp_path):
    dispatcher, calls, _, _ = compound_dispatcher(tmp_path)
    result = dispatcher.maybe_handle('set volume to 25% and how many monthly listeners does Unknown Artist have', 'compound')
    assert result is not None and result.status == 'error'
    assert 'Volume changed from 50% to 25%' in result.answer
    assert sum(args.get('action') == 'set_volume' for name, args in calls) == 1


@pytest.mark.parametrize('query,title,artist', [
    ('play "Love and Hate" and pause', 'Love and Hate', 'Example Artist'),
    ('play September by Earth, Wind and Fire and pause', 'September', 'Earth, Wind and Fire'),
])
def test_compound_separator_preserves_song_titles_and_artist_punctuation(query, title, artist):
    agent, _, calls = fixture_agent(tracks=[{'name': title, 'uri': 'spotify:track:exact', 'artists': [{'name': artist}]}],
        planner=lambda *_: pytest.fail('Preserve the requested title and artist'))
    record = agent.tool_registry.get('spotify_playback')
    playing = [False]
    def playback(args):
        if args['action'] == 'get_state':
            return {'ok': True, 'data': {'is_playing': playing[0], 'track': {'uri': 'spotify:track:exact'}}}
        playing[0] = args['action'] == 'play'
        return record.adapter(args)
    agent.tool_registry._records['spotify_playback'] = replace(record, adapter=playback)
    result = agent.answer(query)
    assert result.status == 'answered', result.summary
    assert title in result.summary and artist in result.summary
    assert [args['action'] for name, args in calls if name == 'spotify_playback'] == ['play', 'pause']
