"""Behavioral coverage for local music ownership, acquisition and playback."""
from io import BytesIO
import json
from pathlib import Path
from threading import Event
import time
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from agent.app_actions.models import AppActionContext,AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.contracts.local_music import MusicImportRequest,MusicSourceEntry,LocalPlaybackRequest,LocalPlayerReport,MusicDownloadRequest
from agent.music_library import MusicLibrary,MusicLibraryError,MusicSources,source_link,youtube_audio_url
from agent.plugins import local_music_api as routes
from agent.plugins.local_music_controls import local_music_contribution
from agent.plugins.registry import PluginRegistry


@pytest.mark.parametrize('tag', [
    '<script id="serialized-server-data">',
    "<SCRIPT ID = 'serialized-server-data'>",
    "<ScRiPt nonce='fixture' id='serialized-server-data' type='application/json'>",
])
def test_apple_metadata_uses_html_script_parsing(monkeypatch, tag):
    import httpx
    payload = [{'contentDescriptor': {'kind': 'song', 'identifiers': {'storeAdamID': '123'}},
                'title': 'A song', 'artistName': 'An artist'}]
    page = '<script id="other">not JSON</script>' + tag + json.dumps(payload) + '</SCRIPT>'
    client_type = httpx.Client
    monkeypatch.setattr('agent.music_library.httpx.Client', lambda **kwargs: client_type(
        **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(200, text=page))))
    _, entries, completeness, _ = MusicSources().apple('https://music.apple.com/us/song/example/123')
    assert len(entries) == 1 and entries[0].title == 'A song'
    assert entries[0].source_id == '123' and completeness == 'complete'


def test_apple_metadata_requires_the_exact_data_script(monkeypatch):
    import httpx
    client_type = httpx.Client
    monkeypatch.setattr('agent.music_library.httpx.Client', lambda **kwargs: client_type(
        **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(
            200, text='<SCRIPT id="unrelated">[]</SCRIPT>'))))
    with pytest.raises(MusicLibraryError, match='did not expose'):
        MusicSources().apple('https://music.apple.com/us/song/example/123')


@pytest.mark.parametrize(('text', 'action', 'query'), [
    ('please can you play A  B on my local music!', 'play', 'A  B'),
    ('Play "A  B"\tfrom\u2003my local library', 'play', '"A  B"'),
    ('pause in local player', 'pause', ''),
    ('could you go to the next track on local music', 'next', ''),
])
def test_local_command_suffix_preserves_title_spacing(text, action, query):
    from agent.plugins.local_music_controls import match_local_music_command
    request = match_local_music_command(text)
    assert request.action_id == 'local_music.playback'
    assert request.arguments == {'action': action, **({'query': query} if query else {})}


def wav_bytes():
    data=BytesIO()
    with wave.open(data,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000);audio.writeframes(b'\0\0'*8000)
    return data.getvalue()


class Sources:
    def __init__(self): self.calls=[];self.fail=False;self.during=None
    def resolve(self,url):
        return 'Songs',[MusicSourceEntry(title='Same song',provider='youtube',source_id='abcdefghijk',source_url='https://www.youtube.com/watch?v=abcdefghijk')]*2,'unknown','Partial public snapshot'
    def download(self,url,directory,cancel):
        self.calls.append(url)
        if self.during:self.during()
        if self.fail:raise MusicLibraryError('Unavailable source')
        path=directory/'audio.wav';path.write_bytes(wav_bytes());return path


@pytest.fixture
def library(tmp_path): return MusicLibrary(tmp_path/'music',sources=Sources(),start_worker=False)


def playlist(library):
    library.import_playlist(MusicImportRequest(url='https://www.youtube.com/playlist?list=PLabcdefghijk'))
    return library.snapshot().collections[0].entries


def imported(library):
    token=library.stage_file('My song.wav',wav_bytes())
    return library.import_file(token)['entry_id']


def test_source_canonicalization_strips_untrusted_options():
    assert source_link('https://music.youtube.com/watch?v=abcdefghijk&feature=share')[2]=='https://www.youtube.com/watch?v=abcdefghijk'
    assert source_link('https://youtu.be/abcdefghijk')[1]=='track'
    assert source_link('https://open.spotify.com/intl-de/playlist/'+'A'*22+'?si=hello')[1]=='playlist'


@pytest.mark.parametrize('url',['file:///C:/Windows/file','https://127.0.0.1/song','https://youtube.com.evil.test/watch?v=abcdefghijk','https://user:secret@youtube.com/watch?v=abcdefghijk','https://youtube.com:9999/watch?v=abcdefghijk','--exec anything','http://youtube.com/watch?v=abcdefghijk'])
def test_untrusted_source_is_rejected(url):
    with pytest.raises(MusicLibraryError): source_link(url)


def test_subscription_links_never_become_download_urls():
    with pytest.raises(MusicLibraryError,match='subscription audio'):
        youtube_audio_url('https://open.spotify.com/track/'+'A'*22)


def test_playlist_order_duplicates_and_missing_audio_survive_restart(library):
    entries=playlist(library)
    assert len(entries)==2 and entries[0].id!=entries[1].id
    restored=MusicLibrary(library.root,sources=Sources(),start_worker=False).snapshot()
    assert [row.title for row in restored.collections[0].entries]==['Same song','Same song']
    assert restored.collections[0].completeness=='unknown'
    assert not any(row.available for row in restored.collections[0].entries)


def test_audio_is_copied_deduplicated_and_can_be_attached_to_an_occurrence(library):
    first=imported(library)
    assert imported(library)==first
    assert library.asset_path(first).read_bytes()==wav_bytes()
    entries=playlist(library)
    library.import_file(library.stage_file('owned.wav',wav_bytes()),entries[1].id)
    group=library.snapshot().collections[0]
    assert [row.available for row in group.entries]==[False,True]
    assert len(list(library.assets.iterdir()))==1


@pytest.mark.parametrize('name,content',[('track.m4p',b'fake'),('track.mp3',b'<html>Login required</html>'),('../../data.json',b'{}'),('empty.wav',b'')])
def test_invalid_or_protected_files_do_not_enter_library(library,name,content):
    with pytest.raises(MusicLibraryError):library.stage_file(name,content)
    assert not library.snapshot().collections and not list(library.staging.iterdir())


def test_download_has_explicit_rights_argument():
    with pytest.raises(ValidationError):MusicDownloadRequest(entry_ids=['song'])
    with pytest.raises(ValidationError):MusicDownloadRequest(entry_ids=['song'],permission_confirmed=False)


def test_jobs_are_idempotent_while_active_and_become_audio_only_after_validation(library):
    entries=playlist(library)
    one=library.enqueue([entries[0].id])
    assert library.enqueue([entries[0].id])['job_ids']==one['job_ids']
    assert not library.snapshot().collections[0].entries[0].available
    assert library.process_next()
    state=library.snapshot()
    assert state.jobs[0].status=='complete'
    assert [entry.available for entry in state.collections[0].entries]==[True,False]
    assert state.collections[0].entries[0].audio_source.startswith('https://www.youtube.com/')


def test_invalid_batch_is_atomic(library):
    entries=playlist(library)
    library.import_playlist(MusicImportRequest(entries=[MusicSourceEntry(title='Spotify song',provider='spotify',source_url='https://open.spotify.com/track/'+'A'*22)]))
    spotify=library.snapshot().collections[0].entries[0]
    with pytest.raises(MusicLibraryError):library.enqueue([entries[0].id,spotify.id])
    assert not library.snapshot().jobs


def test_cancel_during_acquisition_does_not_register_audio(library):
    entry=playlist(library)[0]
    job=library.enqueue([entry.id])['job_ids'][0]
    library.sources.during=lambda:library.manage_job(job,'cancel')
    library.process_next()
    assert library.snapshot().jobs[0].status=='cancelled'
    assert not library.snapshot().collections[0].entries[0].available


def test_failure_is_visible_and_retry_uses_same_entry(library):
    entry=playlist(library)[0];job=library.enqueue([entry.id])['job_ids'][0]
    library.sources.fail=True;library.process_next()
    assert library.snapshot().jobs[0].status=='failed'
    library.sources.fail=False;library.manage_job(job,'retry');library.process_next()
    assert library.snapshot().jobs[0].status=='complete'
    assert len(library.sources.calls)==2


def test_restart_recovers_interrupted_job_and_pauses_player(library):
    identity=imported(library);entry=playlist(library)[0];job=library.enqueue([entry.id])['job_ids'][0]
    library.playback(LocalPlaybackRequest(action='play',entry_ids=[identity]))
    with library.db() as db:db.execute("UPDATE jobs SET status='running' WHERE id=?",(job,))
    restored=MusicLibrary(library.root,sources=Sources(),start_worker=False).snapshot()
    assert restored.jobs[0].status=='failed' and 'Retry' in restored.jobs[0].error
    assert not restored.player.playing and restored.player.queue==[identity]


def test_measured_position_is_preserved_by_volume_and_stale_reports_do_not_ack_commands(library):
    identity=imported(library)
    library.playback(LocalPlaybackRequest(action='play',entry_ids=[identity]))
    owner='owner_abcdefghijklmnop'
    library.report(LocalPlayerReport(owner_id=owner,revision=1,entry_id=identity,playing=True,seconds=.4,duration=1))
    result=library.playback(LocalPlaybackRequest(action='volume',volume=.2))
    assert result['revision']==2 and library.player_state().seconds==.4
    library.report(LocalPlayerReport(owner_id=owner,revision=1,entry_id=identity,seconds=.1))
    assert library.player_state().observed['seconds']==.4


def test_second_window_cannot_steal_an_active_owner(library):
    first=LocalPlayerReport(owner_id='first_abcdefghijklmnop',revision=0)
    second=LocalPlayerReport(owner_id='second_abcdefghijklmnop',revision=0)
    assert library.report(first)['accepted']
    assert not library.report(second)['accepted']
    with library.db() as db:db.execute('UPDATE player SET expires=0')
    assert library.report(second)['accepted']


def test_missing_audio_is_not_playable_and_path_traversal_cannot_read_files(library):
    identity=imported(library);library.asset_path(identity).unlink()
    assert not library.snapshot().collections[0].entries[0].available
    with pytest.raises(MusicLibraryError):library.playback(LocalPlaybackRequest(action='play',entry_ids=[identity]))
    with pytest.raises(MusicLibraryError):library.asset_path('../../.env')


def test_export_roundtrip_preserves_unknown_completeness_and_source_ids(library):
    playlist(library);group=library.snapshot().collections[0];manifest=library.export(group.id)
    library.import_playlist(MusicImportRequest(name=manifest['name'],entries=manifest['entries'],completeness=manifest['completeness'],source_origin=manifest['source_url']))
    copied=library.snapshot().collections[0]
    assert copied.completeness=='unknown' and copied.source_url==group.source_url
    assert [entry.source_id for entry in copied.entries]==['abcdefghijk','abcdefghijk']
    assert str(library.root) not in json.dumps(manifest)


def test_action_catalog_enablement_and_typed_mutations(tmp_path,library):
    root=Path(__file__).parents[2]/'plugins'
    plugins=PluginRegistry(root,state_path=tmp_path/'plugins.json')
    runtime=AppActionRuntime(plugin_registry=plugins)
    runtime.register_plugin_contribution(local_music_contribution(lambda:library))
    request=AppActionRequest(action_id='local_music.playlist',arguments={'url':'https://www.youtube.com/playlist?list=PLabcdefghijk'})
    receipt=runtime.dispatch(request,AppActionContext(source='ui'))
    assert receipt.status=='applied',receipt
    plugins.set_enabled('local_music',False)
    assert not any(item.id.startswith('local_music.') for item in runtime.catalog().actions)
    assert runtime.dispatch(request.model_copy(update={'request_id':'new-request'}),AppActionContext(source='ui')).status=='unavailable'


def test_local_audio_http_ranges_and_cross_origin_guards(library,monkeypatch):
    monkeypatch.setattr(routes,'get_music_library',lambda:library)
    app=FastAPI();app.include_router(routes.router,prefix='/api');app.dependency_overrides[routes.enabled]=lambda:None
    identity=imported(library)
    with TestClient(app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',50000)) as web:
        response=web.get('/api/music/local/audio/'+identity,headers={'Range':'bytes=0-43'})
        assert response.status_code==206 and response.content==wav_bytes()[:44]
        assert response.headers['cache-control']=='no-store'
        body={'owner_id':'owner_abcdefghijklmnop','revision':0}
        assert web.post('/api/music/local/player/report',json=body).status_code==403
        assert web.post('/api/music/local/player/report',json=body,headers={'X-Vellum-Music':'1','Origin':'https://evil.example'}).status_code==403
        assert web.post('/api/music/local/player/report',json=body,headers={'X-Vellum-Music':'1','Origin':'http://127.0.0.1:5173'}).status_code==200


def test_tool_never_uses_ambient_config_cookies_or_shell(monkeypatch,tmp_path):
    seen={}
    class Process:
        returncode=0
        def poll(self):return 0
        def wait(self,timeout):return 0
    def popen(args,**kwargs):seen.update(args=args,kwargs=kwargs);return Process()
    monkeypatch.setattr('agent.music_library.subprocess.Popen',popen)
    MusicSources().run_tool(['--skip-download','--','https://www.youtube.com/watch?v=abcdefghijk'])
    assert '--ignore-config' in seen['args'] and '--no-plugin-dirs' in seen['args'] and '--no-exec' in seen['args']
    assert '--cookies' not in seen['args'] and '--cookies-from-browser' not in seen['args']
    assert not seen['kwargs'].get('shell')


@pytest.mark.parametrize('failure',['access','unavailable','auth'])
def test_spotify_import_uses_same_public_fallback_without_hiding_auth_failure(monkeypatch,failure):
    from unittest.mock import Mock
    from plugins.connectors.spotify.errors import SpotifyAccessDenied,SpotifyResourceUnavailable,SpotifyAuthError
    from agent.plugins import spotify_runtime
    from agent.plugins.spotify_runtime import spotify_public_playlist as public_playlist
    client=Mock();client.request.side_effect=[{'name':'My playlist'}, {'access':SpotifyAccessDenied,'unavailable':SpotifyResourceUnavailable,'auth':SpotifyAuthError}[failure]('Denied')]
    monkeypatch.setattr('agent.plugins.registry.get_plugin_registry',lambda:Mock(is_enabled=lambda name:True))
    monkeypatch.setattr(spotify_runtime,'spotify_client',lambda:client)
    monkeypatch.setattr(spotify_runtime,'spotify_catalog_query_gate',lambda url:(url,None))
    read=Mock(return_value=[{'name':'Public song','artists':['Artist'],'id':'B'*22,'external_url':'https://open.spotify.com/track/'+'B'*22}])
    monkeypatch.setattr(public_playlist,'read_public_playlist',read)
    if failure=='auth':
        with pytest.raises(SpotifyAuthError):MusicSources().spotify('playlist','https://open.spotify.com/playlist/'+'A'*22)
        read.assert_not_called()
    else:
        title,entries,completeness,note=MusicSources().spotify('playlist','https://open.spotify.com/playlist/'+'A'*22)
        assert title=='My playlist' and entries[0].title=='Public song' and completeness=='unknown'
        read.assert_called_once_with('A'*22)


def test_localhost_file_upload_is_readable_in_library_and_audio(tmp_path,library,monkeypatch):
    from agent.app_actions import runtime as runtime_module
    plugins=PluginRegistry(Path(__file__).parents[2]/'plugins',state_path=tmp_path/'plugins.json')
    runtime=AppActionRuntime(plugin_registry=plugins)
    runtime.register_plugin_contribution(local_music_contribution(lambda:library))
    monkeypatch.setattr(runtime_module,'get_app_action_runtime',lambda:runtime)
    monkeypatch.setattr(routes,'get_music_library',lambda:library)
    app=FastAPI();app.include_router(routes.router,prefix='/api');app.dependency_overrides[routes.enabled]=lambda:None
    with TestClient(app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',50000)) as web:
        headers={'Origin':'http://localhost:5173','Sec-Fetch-Site':'cross-site','X-Vellum-Music':'1'}
        response=web.post('/api/music/local/files',headers=headers,files={'file':('Owned song.wav',wav_bytes(),'audio/wav')},data={'entry_id':''})
        assert response.status_code==200,response.text
        receipt=response.json();assert receipt['status']=='applied',receipt
        snapshot=web.get('/api/music/local/library',headers=headers).json()
        entry=snapshot['collections'][0]['entries'][0];assert entry['available'] and entry['title']=='Owned song'
        audio=web.get('/api/music/local/audio/'+entry['id'],headers={'Sec-Fetch-Site':'same-site'})
        assert audio.status_code==200 and audio.content==wav_bytes()


def test_embedded_local_cover_is_projected_and_served_without_changing_audio(library,tmp_path,monkeypatch):
    import base64
    from mutagen.wave import WAVE
    from mutagen.id3 import APIC
    image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJX8AAAAASUVORK5CYII=')
    source=tmp_path/'covered.wav';source.write_bytes(wav_bytes())
    audio=WAVE(source);audio.add_tags();audio.tags.add(APIC(mime='image/png',type=3,data=image));audio.save()
    original=source.read_bytes();entry=library.import_file(library.stage_file('covered.wav',original))['entry_id']
    card=library.snapshot().collections[0].entries[0]
    assert card.model_dump().get('artwork_url')=='/api/music/local/artwork/'+entry
    monkeypatch.setattr(routes,'get_music_library',lambda:library)
    app=FastAPI();app.include_router(routes.router,prefix='/api');app.dependency_overrides[routes.enabled]=lambda:None
    with TestClient(app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',50000)) as web:
        response=web.get(card.artwork_url);assert response.status_code==200 and response.content==image
        assert response.headers['content-type'].startswith('image/png')
    assert library.asset_path(entry).read_bytes()==original


def test_missing_embedded_cover_stays_empty_and_artwork_route_is_guarded(library,monkeypatch):
    identity=imported(library);assert library.snapshot().collections[0].entries[0].artwork_url==''
    monkeypatch.setattr(routes,'get_music_library',lambda:library)
    app=FastAPI();app.include_router(routes.router,prefix='/api');app.dependency_overrides[routes.enabled]=lambda:None
    with TestClient(app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',50000)) as web:
        assert web.get('/api/music/local/artwork/'+identity).status_code==404
        assert web.get('/api/music/local/artwork/'+identity,headers={'Origin':'https://evil.example'}).status_code==403


@pytest.mark.parametrize('image',[b'<svg xmlns="http://www.w3.org/2000/svg"><script>bad()</script></svg>',b'\xff\xd8\xff'+b'x'*(4*1024*1024)],ids=['unsupported-svg','oversized-jpeg'])
def test_unsupported_or_oversized_embedded_cover_does_not_break_audio(library,tmp_path,image):
    from mutagen.wave import WAVE
    from mutagen.id3 import APIC
    source=tmp_path/'covered.wav';source.write_bytes(wav_bytes());audio=WAVE(source);audio.add_tags();audio.tags.add(APIC(mime='image/jpeg',type=3,data=image));audio.save()
    identity=library.import_file(library.stage_file('covered.wav',source.read_bytes()))['entry_id']
    card=library.snapshot().collections[0].entries[0]
    assert card.available and card.artwork_url=='' and library.asset_path(identity).is_file()
