"""Public Music-page reads and selected-source playback contracts."""
import asyncio
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from agent import api
from agent.plugins.spotify_controls import SpotifyPlaybackControlRequest, execute_spotify_control


@pytest.fixture
def service(monkeypatch):
    client = Mock()
    monkeypatch.setattr(api, '_spotify_has_credentials', lambda: True)
    monkeypatch.setattr(api, '_spotify_client', lambda: client)
    return client


def test_saved_emoji_playlist_cards_keep_their_identity_and_pagination(service):
    service.request.return_value = {'items':[{'id':'Emoji', 'uri':'spotify:playlist:Emoji', 'name':'🌙✨',
        'images':[{'url':'https://example.test/cover.jpg'}], 'access_token':'must-not-leak'}],
        'total':51,'next':'https://api.spotify.com/next'}
    page = asyncio.run(api.spotify_browse(kind='playlists',offset=50,limit=1,artist_id=''))
    assert page.total == 51 and page.next_offset == 51
    assert page.items[0].name == '🌙✨' and page.items[0].uri == 'spotify:playlist:Emoji'
    assert 'must-not-leak' not in page.model_dump_json()
    assert service.request.call_args.args == ('GET','/me/playlists')


@pytest.mark.parametrize('owner,editable',[('Me',True),('Spotify',False)])
def test_playlist_details_expose_verified_owner_and_editability(service,owner,editable):
    service.request.return_value = {'id':'Tamil','uri':'spotify:playlist:Tamil','name':'Tamil',
        'description':'My collection','owner':{'id':owner},'images':[]}
    service.get_profile.return_value = {'id':'Me'}
    page = asyncio.run(api.spotify_browse(kind='playlist_details',source_id='Tamil'))
    card = page.items[0]
    assert card.description == 'My collection' and card.owner_id == owner and card.editable is editable
    assert service.request.call_args.args == ('GET','/playlists/Tamil')


def test_playlist_metadata_auth_failure_is_reconnect_error(service):
    service.request.return_value = {'id':'Tamil','name':'Tamil','owner':{'id':'Me'}}
    service.get_profile.side_effect = api.SpotifyAuthError('reconnect')
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.spotify_browse(kind='playlist_details',source_id='Tamil'))
    assert exc.value.status_code == 401


def test_playlist_metadata_rejects_a_different_identity(service):
    service.request.return_value = {'id':'Other','name':'Other'}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.spotify_browse(kind='playlist_details',source_id='Tamil'))
    assert exc.value.status_code == 502
    service.get_profile.assert_not_called()


def test_liked_tracks_are_unwrapped_from_saved_library(service):
    service.request.return_value = {'items':[{'track':{'id':'Song','uri':'spotify:track:Song','name':'Ride',
        'artists':[{'name':'Twenty One Pilots'}], 'album':{'name':'Blurryface','images':[{'url':'https://example.test/cover.jpg'}]}}}], 'total':1}
    page = asyncio.run(api.spotify_browse(kind='liked',offset=0,limit=20,artist_id=''))
    assert page.items[0].kind == 'track' and page.items[0].artists == ['Twenty One Pilots']
    assert page.items[0].album == 'Blurryface'
    assert service.request.call_args.args == ('GET','/me/tracks')


def test_album_search_uses_album_catalog_instead_of_track_search(service):
    service.request.return_value = {'albums':{'items':[{'id':'BF','uri':'spotify:album:BF','name':'Blurryface'}],'total':1}}
    page = asyncio.run(api.spotify_catalog_search('Blurryface',kind='album',offset=0,limit=10))
    assert page.items[0].kind == 'album'
    assert service.request.call_args.kwargs['params']['type'] == 'album'


def test_explicit_mix_link_does_not_search_for_another_users_playlist(service):
    page=asyncio.run(api.spotify_catalog_search('https://open.spotify.com/playlist/PersonalMix?si=abc',kind='track',offset=0,limit=10))
    assert page.items[0].kind == 'playlist' and page.items[0].uri == 'spotify:playlist:PersonalMix'
    assert page.items[0].name == 'Spotify playlist link'  # Unverified title is never invented.
    service.request.assert_not_called()


def test_known_link_uses_connection_collection_metadata_without_catalog_substitution(service):
    service.get_linked_playlists.return_value=[{'id':'Mix','uri':'spotify:playlist:Mix','name':'Your Top Songs 2025','linked':True}]
    page=asyncio.run(api.spotify_catalog_search('https://open.spotify.com/playlist/Mix',kind='track',offset=0,limit=10))
    assert page.items[0].name == 'Your Top Songs 2025' and page.items[0].linked
    service.request.assert_not_called()


def test_playlist_tracks_preserve_unavailable_and_duplicate_source_positions(service):
    track = {'id':'Song','uri':'spotify:track:Song','name':'Ride','duration_ms':214000}
    service.request.return_value = {'items':[{'item':None},{'item':track},{'track':track}], 'total':53,'next':'next'}
    page = asyncio.run(api.spotify_browse(kind='playlist_tracks',offset=50,limit=3,source_id='SavedEmoji'))
    assert [item.position for item in page.items] == [50,51,52]
    assert not page.items[0].playable and page.items[0].name == 'Unavailable track'
    assert page.items[1].uri == page.items[2].uri and page.items[1].duration_ms == 214000
    assert page.next_offset == 53
    assert service.request.call_args.args == ('GET','/playlists/SavedEmoji/items')


def test_album_track_detail_uses_album_tracks_read(service):
    service.request.return_value = {'items':[{'id':'Song','uri':'spotify:track:Song','name':'Track','artists':[{'name':'Artist'}]}],'total':1}
    page = asyncio.run(api.spotify_browse(kind='album_tracks',offset=0,limit=50,source_id='Album'))
    assert page.items[0].artists == ['Artist'] and page.items[0].position == 0
    assert service.request.call_args.args == ('GET','/albums/Album/tracks')


def test_denied_playlist_reads_exact_public_song_list(service,monkeypatch):
    identity='A'*22
    service.request.side_effect=api._spotify_module.errors.SpotifyAccessDenied('Restricted')
    monkeypatch.setattr(api.spotify_public_playlist,'cached_public_playlist',lambda _identity:None)
    seen=[]
    def read(playlist_id):
        seen.append(playlist_id)
        return [{'id':'Song','uri':'spotify:track:Song','kind':'track','name':'Public song','position':0,'playable':True}]
    monkeypatch.setattr(api.spotify_public_playlist,'read_public_playlist',read)
    result=asyncio.run(api.spotify_browse(kind='playlist_tracks',source_id=identity,offset=0,limit=50))
    assert seen==[identity] and result.items[0].name=='Public song'
    assert result.source=='public_embed' and result.completeness=='unknown'


def test_expired_auth_does_not_trigger_public_fallback(service,monkeypatch):
    service.request.side_effect=api.SpotifyAuthError('Reconnect')
    read=Mock();monkeypatch.setattr(api.spotify_public_playlist,'read_public_playlist',read)
    monkeypatch.setattr(api.spotify_public_playlist,'cached_public_playlist',lambda _:None)
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.spotify_browse(kind='playlist_tracks',source_id='A'*22,offset=0,limit=50))
    assert error.value.status_code==401
    read.assert_not_called()


def test_artwork_route_validates_and_projects_exact_track_metadata(service,monkeypatch):
    identity='A'*22
    monkeypatch.setattr(api,'_plugin_registry',lambda:Mock(is_enabled=lambda plugin:plugin=='spotify'))
    read=Mock(return_value=[{'id':identity,'artwork_url':'https://i.scdn.co/image/example'}])
    monkeypatch.setattr(api.spotify_public_playlist,'read_track_artworks',read)
    page=asyncio.run(api.spotify_track_artwork(identity))
    assert page.items[0].id==identity and page.items[0].artwork_url.startswith('https://i.scdn.co/')
    read.assert_called_once_with([identity],wait_seconds=.35)
    with pytest.raises(HTTPException) as error:asyncio.run(api.spotify_track_artwork('../secret'))
    assert error.value.status_code==422


@pytest.mark.parametrize('connected,enabled,status',[(False,True,401),(True,False,409)])
def test_artwork_requires_connected_enabled_plugin(monkeypatch,connected,enabled,status):
    monkeypatch.setattr(api,'_spotify_has_credentials',lambda:connected)
    monkeypatch.setattr(api,'_plugin_registry',lambda:Mock(is_enabled=lambda plugin:enabled))
    read=Mock()
    monkeypatch.setattr(api.spotify_public_playlist,'read_track_artworks',read)
    with pytest.raises(HTTPException) as error:asyncio.run(api.spotify_track_artwork('A'*22))
    assert error.value.status_code==status
    read.assert_not_called()


def test_detail_requires_source_before_provider_read(service):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.spotify_browse(kind='playlist_tracks',offset=0,limit=50,source_id=''))
    assert exc.value.status_code == 422
    service.request.assert_not_called()


def test_catalog_search_preserves_private_query_gate(service):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.spotify_catalog_search('private@example.test',kind='track',offset=0,limit=10))
    assert exc.value.status_code == 422
    service.request.assert_not_called()


def test_library_failure_is_not_converted_into_a_zero_count(service):
    service.request.side_effect = api.SpotifyAuthError('reconnect')
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.spotify_browse(kind='playlists',offset=0,limit=20,artist_id=''))
    assert exc.value.status_code == 401


def test_playlist_access_denial_is_not_reported_as_backend_unreachable(service):
    class AccessDenied(api._spotify_module.tools.SpotifyError):
        code = 'access_denied'
    service.request.side_effect = AccessDenied('Spotify does not allow this app to access this resource')
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.spotify_browse(kind='playlist_tracks',offset=0,limit=1,source_id='Denied'))
    assert exc.value.status_code == 403
    assert 'does not allow' in exc.value.detail


@pytest.mark.parametrize('arguments',[
    {'action':'pause','context_uri':'spotify:playlist:Emoji'},
    {'action':'play','context_uri':'spotify:artist:A'},
    {'action':'play','uris':['https://malicious.test']},
    {'action':'play','query':'Ride','uris':['spotify:track:Song']},
    {'action':'play','uris':['spotify:track:Song'],'offset_position':2},
])
def test_selected_source_is_validated_before_playback(arguments):
    with pytest.raises(ValidationError): SpotifyPlaybackControlRequest.model_validate(arguments)


def test_selected_album_and_liked_queue_use_canonical_playback_action(monkeypatch):
    from agent.plugins import spotify_controls
    client = Mock()
    monkeypatch.setattr(spotify_controls,'spotify_client',lambda:client)
    handler = Mock(return_value='{"ok":true,"data":{}}')
    monkeypatch.setattr(spotify_controls,'spotify_playback',handler)
    execute_spotify_control({'arguments':{'action':'play','context_uri':'spotify:album:BF'}})
    assert handler.call_args.args[0]['context_uri'] == 'spotify:album:BF'
    execute_spotify_control({'arguments':{'action':'play','uris':['spotify:track:Song','spotify:track:Next']}})
    assert handler.call_args.args[0]['uris'] == ['spotify:track:Song','spotify:track:Next']
    execute_spotify_control({'arguments':{'action':'play','context_uri':'spotify:album:BF','offset_position':5}})
    assert handler.call_args.args[0]['offset'] == {'position':5}
    assert 'offset_position' not in handler.call_args.args[0]


def test_music_agent_resolves_linked_mix_and_describes_collection_provenance():
    from agent.contracts.music import MusicPlan
    from agent.tools.capabilities.spotify_service import SpotifyCapabilityService
    rows=[{'id':'saved','name':'Tamil/Telugu Songs','uri':'spotify:playlist:saved'},
          {'id':'mix','name':'Rizz Mix','uri':'spotify:playlist:mix','linked':True}]
    def invoke(name,args):
        assert name=='spotify_playlists' and args['action']=='list'
        return {'items':rows,'total':2,'next':None}
    service=SpotifyCapabilityService()
    assert service.resolve_playlist(MusicPlan(operation='play_playlist',query='Rizz Mix'),invoke)['uri']=='spotify:playlist:mix'
    reply=service.execute(MusicPlan(operation='list_playlists'),invoke)
    assert '2 playlists (1 returned by Spotify and 1 linked in Vellum)' in reply


def test_unexposed_playlist_contents_return_404_instead_of_unreachable(service):
    class Unexposed(api._spotify_module.tools.SpotifyError):code='resource_unavailable'
    service.request.side_effect=Unexposed('Spotify has not exposed this resource to Vellum')
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.spotify_browse(kind='playlist_tracks',offset=0,limit=50,source_id='Mix'))
    assert exc.value.status_code==404 and 'not exposed' in exc.value.detail
