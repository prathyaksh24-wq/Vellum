"""Exact-link public metadata fallback; no media or credential transfer."""
import json
import httpx
import pytest
from plugins.connectors.spotify import public_playlist as public
from agent.contracts.music_surface import public_playlist_page

IDENTITY='A'*22


def page(rows,identity=IDENTITY):
    data={'props':{'pageProps':{'state':{'data':{'entity':{'type':'playlist','id':identity,
        'uri':'spotify:playlist:'+identity,'title':'Linked playlist','trackList':rows}}}}}}
    return '<script type="application/json" nonce="example" id="__NEXT_DATA__">'+json.dumps(data)+'</script>'


def track(identity='B'*22):
    return {'uri':'spotify:track:'+identity,'title':'A song','subtitle':'Artist, Other artist','duration':180000,
        'audioPreview':{'url':'https://secret.example/never-export'},'access_token':'never-export'}


@pytest.fixture(autouse=True)
def clear_cache():
    public._cache.clear()
    public._artwork_cache.clear()
    yield
    public._cache.clear()
    public._artwork_cache.clear()


def test_keeps_duplicate_occurrences_and_unavailable_source_positions():
    rows=public.parse_public_playlist(page([track(),{'title':'Unavailable'},track()]),IDENTITY)
    assert len(rows)==3 and rows[0]['uri']==rows[2]['uri']
    assert [row['position'] for row in rows]==[0,1,2]
    assert not rows[1]['playable']
    assert 'never-export' not in json.dumps(rows)


def test_public_count_is_not_presented_as_verified_complete_playlist():
    rows=public.parse_public_playlist(page([track(),track()]),IDENTITY)
    result=public_playlist_page(rows,0,1)
    assert result.source=='public_embed' and result.completeness=='unknown'
    assert result.total==2 and result.next_offset==1
    assert result.items[0].position==0
    assert 'may omit songs' in result.note
    assert public_playlist_page(rows,1,1).items[0].position==1


def test_identity_mismatch_does_not_substitute_another_playlist():
    with pytest.raises(public.PublicPlaylistUnavailable):
        public.parse_public_playlist(page([track()],identity='C'*22),IDENTITY)


@pytest.mark.parametrize('identity',['../secrets','https://evil.test','bad',IDENTITY+'?cookies=secret'])
def test_untrusted_ids_never_reach_network(identity):
    with pytest.raises(public.PublicPlaylistUnavailable):public.read_public_playlist(identity)


def test_fixed_public_fetch_has_no_cookies_or_authorization_and_uses_bounded_cache():
    requests=[]
    def handle(request):
        requests.append(request)
        return httpx.Response(200,text=page([track()]))
    transport=httpx.MockTransport(handle)
    one=public.read_public_playlist(IDENTITY,transport=transport)
    public.read_public_playlist(IDENTITY,transport=transport)
    assert len(requests)==1
    request=requests[0]
    assert str(request.url)=='https://open.spotify.com/embed/playlist/'+IDENTITY
    assert 'authorization' not in request.headers and 'cookie' not in request.headers
    assert one[0]['name']=='A song'


def test_redirect_is_rejected_without_following_external_host():
    urls=[]
    def handle(request):
        urls.append(str(request.url));return httpx.Response(302,headers={'Location':'https://evil.test/'})
    with pytest.raises(public.PublicPlaylistUnavailable):public.read_public_playlist(IDENTITY,transport=httpx.MockTransport(handle))
    assert urls==['https://open.spotify.com/embed/playlist/'+IDENTITY]


def test_empty_public_view_remains_unavailable():
    with pytest.raises(public.PublicPlaylistUnavailable):public.parse_public_playlist(page([]),IDENTITY)


def test_link_action_preserves_exact_uris_in_canonical_connection(tmp_path,monkeypatch):
    from pathlib import Path
    from unittest.mock import Mock
    from agent.app_actions.models import AppActionContext,AppActionRequest
    from agent.app_actions.runtime import AppActionRuntime
    from agent.plugins.registry import PluginRegistry
    from agent.plugins import spotify_controls
    client=Mock();client.remember_playlist_links.return_value={'items':[],'total':2}
    monkeypatch.setattr(spotify_controls,'spotify_client',lambda:client)
    runtime=AppActionRuntime(plugin_registry=PluginRegistry(Path(__file__).parents[2]/'plugins',state_path=tmp_path/'plugins.json'))
    runtime.register_plugin_contribution(spotify_controls.spotify_plugin_contribution(authenticated=lambda:True))
    uris=['spotify:playlist:'+IDENTITY,'spotify:playlist:'+'C'*22]
    result=runtime.dispatch(AppActionRequest(action_id='spotify.playlists.link',arguments={'uris':uris}),AppActionContext(source='ui'))
    assert result.status=='applied' and result.result['count']==2
    client.remember_playlist_links.assert_called_once_with(uris)


def test_artwork_metadata_is_cached_and_never_sends_authentication():
    requests=[]
    def handle(request):
        requests.append(request)
        return httpx.Response(200,json={'thumbnail_url':'https://i.scdn.co/image/example','html':'must-not-leak','access_token':'must-not-leak'})
    first=public.read_track_artworks([IDENTITY,IDENTITY],transport=httpx.MockTransport(handle))
    assert first==[{'id':IDENTITY,'artwork_url':'https://i.scdn.co/image/example'}]
    assert public.read_track_artworks([IDENTITY],transport=httpx.MockTransport(handle))==first
    assert len(requests)==1 and 'authorization' not in requests[0].headers and 'cookie' not in requests[0].headers
    assert requests[0].url.params['url']=='https://open.spotify.com/track/'+IDENTITY
    assert 'must-not-leak' not in json.dumps(first)


@pytest.mark.parametrize('url',['http://i.scdn.co/image/a','https://evil.example/a','https://user:secret@i.scdn.co/image/a','https://i.scdn.co:9999/image/a'])
def test_artwork_rejects_untrusted_image_destinations(url):
    result=public.read_track_artworks([IDENTITY],transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'thumbnail_url':url})))
    assert result==[{'id':IDENTITY,'artwork_url':''}]


def test_missing_artwork_degrades_to_a_placeholder_without_failing_playlist():
    result=public.read_track_artworks([IDENTITY],transport=httpx.MockTransport(lambda _:httpx.Response(503)))
    assert result[0]['artwork_url']==''


def test_artwork_parallel_work_is_bounded_and_shared_for_same_track():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock
    import time
    active,maximum,seen=0,0,[]
    lock=Lock()
    def handle(request):
        nonlocal active,maximum
        with lock:active+=1;maximum=max(maximum,active);seen.append(request.url.params['url'])
        time.sleep(.02)
        with lock:active-=1
        return httpx.Response(200,json={'thumbnail_url':'https://i.scdn.co/image/example'})
    identities=[str(index).zfill(22) for index in range(10)]
    transport=httpx.MockTransport(handle)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=[pool.submit(public.read_track_artworks,identities,transport=transport) for _ in range(2)]
        assert all(len(result.result())==10 for result in results)
    assert maximum<=4 and len(seen)==10


def test_ready_artwork_does_not_wait_for_another_slow_track():
    from threading import Event
    import time
    release=Event();slow='S'*22;fast='F'*22
    def handle(request):
        if request.url.params['url'].endswith(slow):release.wait(2)
        return httpx.Response(200,json={'thumbnail_url':'https://i.scdn.co/image/example'})
    try:
        started=time.monotonic()
        result=public.read_track_artworks([slow,fast],transport=httpx.MockTransport(handle),wait_seconds=.25)
        assert time.monotonic()-started<1
        assert result[0]['pending'] is True and result[1]['artwork_url']
    finally:release.set()
    assert public.read_track_artworks([slow],transport=httpx.MockTransport(handle))[0]['artwork_url']
