"""Instant player instructions: parsing, Local Music execution, provider choice, specialist shortcut."""
import time

import pytest

from agent.contracts.local_music import LocalPlaybackRequest, LocalPlayerReport
from agent.contracts.music import match_player_request
from agent.music_library import MusicLibrary
from agent import music_player
from io import BytesIO
import wave

from tests.test_local_music import Sources


def wav_bytes(frames=8000):
    data = BytesIO()
    with wave.open(data, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000); audio.writeframes(bytes(2 * frames))
    return data.getvalue()


@pytest.mark.parametrize('text, op, extra', [
    ('what song is currently playing>', 'info', {'detail': 'song'}),
    ('i need the name of the song', 'info', {'detail': 'song'}),
    ("what's the song name?", 'info', {'detail': 'song'}),
    ('what album is this from', 'info', {'detail': 'album'}),
    ('who sings this', 'info', {'detail': 'artist'}),
    ("what's next", 'info', {'detail': 'next'}),
    ("what's in the queue", 'info', {'detail': 'queue'}),
    ('which playlist is this', 'info', {'detail': 'playlist'}),
    ('like this song', 'like', {}),
    ('add this song to my liked songs', 'like', {}),
    ('unlike this song', 'unlike', {}),
    ('increase the volume', 'volume_by', {'volume': 10}),
    ('turn the volume down by 20%', 'volume_by', {'volume': -20}),
    ('set volume to 40%', 'volume_set', {'volume': 40}),
    ('skip 30 secs', 'seek_by', {'seconds': 30}),
    ('go back 30 seconds', 'seek_by', {'seconds': -30}),
    ('forward 1 min', 'seek_by', {'seconds': 60}),
    ('restart the song', 'restart', {}),
    ('mute', 'mute', {}),
    ('shuffle on', 'shuffle', {'enabled': True}),
    ('repeat this song', 'repeat', {'repeat': 'one'}),
    ("what's playing on spotify", 'info', {'provider': 'spotify'}),
    ('skip 30 secs in local music', 'seek_by', {'provider': 'local'}),
])
def test_player_phrases(text, op, extra):
    command = match_player_request(text)
    assert command is not None and command.op == op
    for key, value in extra.items():
        assert getattr(command, key) == value


@pytest.mark.parametrize('text', ['what is this', 'who is this', "what's on", 'save', 'skip 2',
    'what is the capital of france', 'play blinding lights', 'what playlists do i have',
    'what is the best song ever', 'tell me about the album Thriller'])
def test_other_requests_stay_with_the_model(text):
    assert match_player_request(text) is None


@pytest.fixture
def library(tmp_path):
    return MusicLibrary(tmp_path / 'music', sources=Sources(), start_worker=False)


def _song(library, name):
    return library.import_file(library.stage_file(name + '.wav', wav_bytes(8000 + 37 * len(name) + ord(name[0]))))['entry_id']


def _report(library, entry_id, seconds, playing=True):
    state = library.player_state()
    library.report(LocalPlayerReport(owner_id='owner-0123456789ab', revision=state.revision, entry_id=entry_id,
                                     playing=playing, seconds=seconds, duration=200))


def test_local_now_playing_follows_the_player_not_the_first_song(library):
    first, second = _song(library, 'First'), _song(library, 'Second')
    played = library.playback(LocalPlaybackRequest(action='play', entry_ids=[first, second]))
    assert played['_message'] == 'Playing “First”.'
    skipped = library.playback(LocalPlaybackRequest(action='next'))
    assert skipped['_message'] == 'Playing “Second”.'
    _report(library, second, 5)
    assert library.now_playing()['_message'] == 'Now playing “Second”.'
    assert library.now_playing('playlist')['_message'] == '“Second” is playing from your “Imported” playlist.' \
        or 'is playing from your' in library.now_playing('playlist')['_message']


def test_local_seek_volume_and_mute_are_relative_to_live_state(library):
    song = _song(library, 'Song')
    library.playback(LocalPlaybackRequest(action='play', entry_ids=[song]))
    _report(library, song, 40)
    result = library.playback(LocalPlaybackRequest(action='seek_by', delta=30))
    assert result['_message'] == 'Skipped ahead 30 seconds.'
    assert 70 <= library.player_state().seconds < 72
    library.playback(LocalPlaybackRequest(action='seek_by', delta=-500))
    assert library.player_state().seconds == 0
    assert library.playback(LocalPlaybackRequest(action='volume_by', delta=0.1))['_message'] == 'Volume is 80%.'
    assert library.playback(LocalPlaybackRequest(action='mute'))['_message'] == 'Muted.'
    assert library.playback(LocalPlaybackRequest(action='unmute'))['_message'] == 'Unmuted. Volume is 80%.'


def test_local_like_adds_to_liked_songs_and_unlike_keeps_playback(library):
    song = _song(library, 'Loved')
    library.playback(LocalPlaybackRequest(action='play', entry_ids=[song]))
    liked = library.playback(LocalPlaybackRequest(action='like'))
    assert liked['liked'] is True and liked['_message'] == 'Added “Loved” to your Liked Songs.'
    assert library.playback(LocalPlaybackRequest(action='like'))['changed'] is False
    group = next(g for g in library.snapshot().collections if g.id == 'liked')
    assert group.name == 'Liked Songs' and len(group.entries) == 1
    assert library.now_playing('liked')['liked'] is True
    # Play from Liked Songs, then unlike: the queue moves to the original copy.
    library.playback(LocalPlaybackRequest(action='play', entry_ids=[group.entries[0].id]))
    removed = library.playback(LocalPlaybackRequest(action='unlike'))
    assert removed['liked'] is False
    assert library.player_state().queue == [song]
    assert all(g.id != 'liked' for g in library.snapshot().collections)


def test_provider_choice_prefers_the_player_that_is_playing(monkeypatch):
    class State:
        def __init__(self, playing, queue=('a',)):
            self.owner_available, self.queue, self.observed = True, list(queue), {'playing': playing}
    command = match_player_request('what song is this')
    monkeypatch.setattr(music_player, '_local_state', lambda available: State(True))
    monkeypatch.setattr(music_player, '_spotify_state', lambda available: (True, 'ready', False, 0.0, 0.0))
    assert music_player.choose_player(command, local_available=True, spotify_available=True, require_present=False) == 'local'
    monkeypatch.setattr(music_player, '_local_state', lambda available: State(False))
    monkeypatch.setattr(music_player, '_spotify_state', lambda available: (True, 'ready', True, 0.0, 0.0))
    assert music_player.choose_player(command, local_available=True, spotify_available=True, require_present=False) == 'spotify'
    request = music_player.player_action(match_player_request('like this song'), 'spotify')
    assert request.action_id == 'spotify.playback.control' and request.arguments == {'action': 'save_current'}
    request = music_player.player_action(match_player_request('skip 30 secs'), 'spotify')
    assert request.arguments == {'action': 'seek_by', 'delta': 30000}
    # Ambiguous words ("like it") need a loaded player.
    monkeypatch.setattr(music_player, '_local_state', lambda available: None)
    monkeypatch.setattr(music_player, '_spotify_state', lambda available: (True, 'disabled', False, 0.0, 0.0))
    assert music_player.match_player_action('like it', local_available=True, spotify_available=True) is None


def test_spotify_relative_controls_use_live_state(monkeypatch):
    from agent.plugins import spotify_controls

    calls = []
    state = {'track': {'uri': 'spotify:track:abc', 'name': 'Song'}, 'artists': ['Artist'], 'progress_ms': 10000,
             'duration_ms': 200000, 'is_playing': True, 'device': {'id': 'dev', 'volume_percent': 50}}
    monkeypatch.setattr(spotify_controls, 'spotify_client', lambda: object())
    monkeypatch.setattr(spotify_controls, '_spotify_live', lambda service: state)
    monkeypatch.setattr(spotify_controls, 'spotify_playback', lambda body, service=None: calls.append(body) or '{"ok": true, "data": {}}')
    library_calls = []
    monkeypatch.setattr(spotify_controls._spotify_module.tools, 'spotify_library', lambda body, service=None: library_calls.append(body) or '{"ok": true, "data": {}}')
    seek = spotify_controls.execute_spotify_control({'arguments': {'action': 'seek_by', 'delta': 30000}})
    assert calls[-1] == {'action': 'seek', 'position_ms': 40000, 'device_id': 'dev'}
    assert seek['_message'] == 'Skipped ahead 30 seconds.'
    volume = spotify_controls.execute_spotify_control({'arguments': {'action': 'volume_by', 'delta': 10}})
    assert calls[-1]['volume_percent'] == 60 and volume['_message'] == 'Volume is 60%.'
    liked = spotify_controls.execute_spotify_control({'arguments': {'action': 'save_current'}})
    assert library_calls[-1] == {'action': 'save', 'kind': 'tracks', 'uris': ['spotify:track:abc']}
    assert liked['_message'] == 'Added “Song” by Artist to your Liked Songs.'
    status = spotify_controls.execute_spotify_status({'arguments': {'detail': 'song'}})
    assert status['_message'] == 'Now playing “Song” by Artist.'


def test_specialist_with_a_direct_handler_skips_the_model_loop():
    from types import SimpleNamespace
    from agent.agents.base import SpecialistResponse
    from agent.profiles.runner import run_profile

    class Model:
        def bind_tools(self, tools):
            raise AssertionError('model loop should not run')
    answer = SpecialistResponse(agent='MusicAgent', status='answered', summary='Now playing “Song”.')
    profile = SimpleNamespace(id='MusicAgent', tools=SimpleNamespace(allow=[], require_confirmation=[]),
        memory=SimpleNamespace(receive_from=[]), skills=SimpleNamespace(allow=[]),
        delegation=SimpleNamespace(timeout_seconds=5, max_iterations=3), response_schema='')
    executor = SimpleNamespace(tool_registry=None, handles_directly=lambda goal: True)
    result = run_profile(profile=profile, executor=executor, model=Model(), goal='what song is playing', context='',
        thread_id='t', memory_reader=lambda *a: {}, skill_reader=lambda name: '', action_handler=lambda: answer)
    assert result is answer


def test_song_name_right_after_skip_names_the_new_song(library):
    first, second = _song(library, 'First'), _song(library, 'Second')
    library.playback(LocalPlaybackRequest(action='play', entry_ids=[first, second]))
    _report(library, first, 50)
    library.playback(LocalPlaybackRequest(action='next'))
    # The player has not reported since the skip; its last report is the old song.
    assert library.now_playing()['title'] == 'Second'
    library.playback(LocalPlaybackRequest(action='seek', seconds=90))
    library.playback(LocalPlaybackRequest(action='volume', volume=0.5))
    assert library.player_state().seconds == 90


def test_play_something_queues_more_than_one_song(library):
    _song(library, 'One'), _song(library, 'Two'), _song(library, 'Three')
    library.playback(LocalPlaybackRequest(action='play', pick_any=True))
    assert len(library.player_state().queue) == 3
    assert library.now_playing('next')['_message'].startswith('Up next: “')


@pytest.mark.parametrize('text, op, detail', [
    ('what is the name if the sing', 'info', 'song'),
    ('waht song is plyaing', 'info', 'song'),
    ('skp 30 secs', 'seek_by', 'song'),
    ('incrase the volume', 'volume_by', 'song'),
    ('lik this song', 'like', 'song'),
    ('paues', 'pause', 'song'),
    ('from which playlist the song is playing from', 'info', 'playlist'),
    ('what playlist is this song in', 'info', 'playlist'),
    ('what is the next song after this', 'info', 'next'),
    ('who sang this', 'info', 'artist'),
])
def test_typos_and_free_word_order(text, op, detail):
    command = match_player_request(text)
    assert command is not None and (command.op, command.detail) == (op, detail)


@pytest.mark.parametrize('text', ['what is this song about', 'which playlist should i add this to', 'what is life', 'shop'])
def test_typo_tolerance_does_not_capture_conversation(text):
    assert match_player_request(text) is None


def test_paused_players_answer_from_the_one_used_last(monkeypatch):
    class State:
        owner_available, queue = True, ['a']
        def __init__(self, last): self.observed = {'playing': False, 'last_playing_at': last}
    command = match_player_request('which playlist is this song from')
    monkeypatch.setattr(music_player, '_local_state', lambda available: State(2000.0))
    monkeypatch.setattr(music_player, '_spotify_state', lambda available: (True, 'ready', False, 0.0, 1000.0))
    assert music_player.choose_player(command, local_available=True, spotify_available=True, require_present=False) == 'local'
    monkeypatch.setattr(music_player, '_local_state', lambda available: State(500.0))
    assert music_player.choose_player(command, local_available=True, spotify_available=True, require_present=False) == 'spotify'


def test_local_playlist_names_ignore_singular_plural_and_case(library):
    song = _song(library, 'Oldie')
    library.import_playlist  # library helper exists; create a named playlist directly
    with library.db() as db:
        db.execute("INSERT INTO collections(id,name,source_url,completeness,note,pending_import,auto_import) VALUES('c1','Classics','','complete','',0,0)")
        asset = db.execute('SELECT asset_id FROM entries WHERE id=?', (song,)).fetchone()[0]
        db.execute("INSERT INTO entries VALUES('e1','c1',0,?,?)", ('{"title":"Oldie"}', asset))
    assert library.has_playlist('my classic playlist') and library.has_playlist('CLASSICS')
    played = library.playback(LocalPlaybackRequest(action='play', query='my classic playlist'))
    assert played['_message'] == 'Playing your “Classics” playlist, starting with “Oldie”.'


@pytest.mark.parametrize('text', ['play something from my local playlists', 'play somethign from my local player',
                                  'play my local playlists', 'play a song from my local music'])
def test_play_anything_from_local(text, monkeypatch):
    from agent.plugins.local_music_controls import match_local_music_command
    command = match_local_music_command(text)
    assert command is not None and command.arguments == {'action': 'play', 'pick_any': True}


def test_spotify_playlist_by_name_is_instant(monkeypatch):
    monkeypatch.setattr(music_player, '_spotify_saved_playlists', lambda: [
        {'name': 'Classics', 'uri': 'spotify:playlist:abc'}, {'name': 'Hindhi', 'uri': 'spotify:playlist:def'}])
    monkeypatch.setattr('agent.plugins.spotify_runtime.spotify_is_authenticated', lambda: True)
    request = music_player.match_playlist_action('play my classic playlist', spotify_available=True)
    assert request.arguments == {'action': 'play', 'context_uri': 'spotify:playlist:abc', 'context_name': 'Classics'}
    assert music_player.match_playlist_action('play my jazz playlist', spotify_available=True) is None
    assert music_player.match_playlist_action('play my local playlists', spotify_available=True) is None
