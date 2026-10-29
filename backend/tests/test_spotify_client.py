import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest

from plugins.connectors.spotify.auth import SpotifyAuthStore
from plugins.connectors.spotify.client import SpotifyClient
from plugins.connectors.spotify.errors import (
    SpotifyAuthError,
    SpotifyNoActiveDevice,
    SpotifyPremiumRequired,
    SpotifyRateLimited,
)


@pytest.fixture
def auth_store(tmp_path):
    store = SpotifyAuthStore(tmp_path)
    store.save_tokens(
        {
            "client_id": "client-123",
            "access_token": "old-token",
            "refresh_token": "refresh-token",
            "expires_at": time.time() + 3600,
        }
    )
    return store


def test_401_refreshes_and_retries_once(auth_store):
    calls = []

    def handler(request):
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "new-token", "expires_in": 3600})
        if request.headers["Authorization"] == "Bearer old-token":
            return httpx.Response(401, json={"error": {"message": "expired"}})
        return httpx.Response(200, json={"is_playing": True})

    client = SpotifyClient(auth_store=auth_store, transport=httpx.MockTransport(handler))

    result = client.request("GET", "/me/player")

    assert result["is_playing"] is True
    assert calls == ["GET /v1/me/player", "POST /api/token", "GET /v1/me/player"]
    assert auth_store.load_tokens()["access_token"] == "new-token"
    assert auth_store.load_tokens()["refresh_token"] == "refresh-token"


def test_playlist_permission_denial_has_a_distinct_safe_code(auth_store):
    from plugins.connectors.spotify.errors import SpotifyAPIError
    client=SpotifyClient(auth_store=auth_store,transport=httpx.MockTransport(lambda request: httpx.Response(403,json={'error':{'message':'private upstream response'}})))
    with pytest.raises(SpotifyAPIError) as exc:
        client.request('GET','/playlists/Saved/items')
    assert exc.value.code == 'access_denied'
    assert 'private upstream response' not in str(exc.value)


def test_204_is_inactive_state(auth_store):
    transport = httpx.MockTransport(lambda request: httpx.Response(204))

    result = SpotifyClient(auth_store=auth_store, transport=transport).request(
        "GET", "/me/player/currently-playing"
    )

    assert result == {"is_playing": False, "item": None}


@pytest.mark.parametrize("method,path", [("PUT", "/me/player/play"), ("POST", "/me/player/next")])
def test_empty_command_acknowledgement_does_not_report_stopped_playback(auth_store, method, path):
    client = SpotifyClient(auth_store, transport=httpx.MockTransport(lambda request: httpx.Response(204)))

    assert client.request(method, path) == {}


def test_expiring_token_is_refreshed_before_playback_request(auth_store):
    saved = auth_store.load_tokens()
    auth_store.save_tokens({**saved, "expires_at": time.time() + 10})
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer fresh"
        return httpx.Response(200, json={"is_playing": True})

    assert SpotifyClient(auth_store, transport=httpx.MockTransport(handler)).request("GET", "/me/player")["is_playing"] is True
    assert calls == ["/api/token", "/v1/me/player"]


def test_concurrent_expired_requests_share_one_refresh_across_clients(auth_store):
    old_requests = Barrier(2)
    refreshes = []

    def handler(request):
        if request.url.path == "/api/token":
            refreshes.append(request)
            return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
        if request.headers["Authorization"] == "Bearer old-token":
            old_requests.wait(timeout=2)
            return httpx.Response(401)
        return httpx.Response(200, json={"is_playing": True})

    clients = [SpotifyClient(SpotifyAuthStore(auth_store.root), transport=httpx.MockTransport(handler)) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda client: client.request("GET", "/me/player"), clients))

    assert all(result["is_playing"] for result in results)
    assert len(refreshes) == 1


def test_rotating_credentials_remain_usable_across_ninety_simulated_days(auth_store, monkeypatch):
    now = [time.time()]
    monkeypatch.setattr(time, "time", lambda: now[0])
    refreshes = []

    def handler(request):
        if request.url.path == "/api/token":
            refreshes.append(request.content.decode())
            index = len(refreshes)
            return httpx.Response(200, json={"access_token": f"access-{index}", "refresh_token": f"refresh-{index}", "expires_in": 3600})
        assert request.headers["Authorization"] == f"Bearer access-{len(refreshes)}"
        return httpx.Response(204)

    for _ in range(90):
        now[0] += 24 * 3600
        # Recreate the client and store as happens across API calls/restarts.
        client = SpotifyClient(SpotifyAuthStore(auth_store.root), transport=httpx.MockTransport(handler))
        assert client.request("PUT", "/me/player/play") == {}

    assert len(refreshes) == 90
    assert all(f"refresh_token=refresh-{index}" in refreshes[index] for index in range(1, 90))
    assert auth_store.load_tokens()["refresh_token"] == "refresh-90"


def test_repeated_unauthorized_response_does_not_loop(auth_store):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/token":
            return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
        return httpx.Response(401)

    with pytest.raises(SpotifyAuthError):
        SpotifyClient(auth_store, transport=httpx.MockTransport(handler)).request("POST", "/me/player/next")
    assert calls == ["/v1/me/player/next", "/api/token", "/v1/me/player/next"]


def test_uncertain_skip_timeout_is_not_replayed(auth_store):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout("response lost", request=request)

    with pytest.raises(httpx.ReadTimeout):
        SpotifyClient(auth_store, transport=httpx.MockTransport(handler)).request("POST", "/me/player/next")
    assert calls == ["/v1/me/player/next"]


def test_2xx_plain_text_player_acknowledgement_is_success(auth_store):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="opaque-player-command-id")
    )

    result = SpotifyClient(auth_store=auth_store, transport=transport).request(
        "POST", "/me/player/next"
    )

    assert result == {}


def test_429_uses_retry_after(auth_store):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(429, headers={"Retry-After": "12"})
    )

    with pytest.raises(SpotifyRateLimited) as caught:
        SpotifyClient(auth_store=auth_store, transport=transport).request("GET", "/me/player")

    assert caught.value.retry_after == 12


@pytest.mark.parametrize(
    ("message", "error_type"),
    [
        ("Player command failed: No active device found", SpotifyNoActiveDevice),
        ("PREMIUM_REQUIRED: Premium required", SpotifyPremiumRequired),
    ],
)
def test_403_maps_safe_domain_errors(auth_store, message, error_type):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(403, json={"error": {"message": message}})
    )

    with pytest.raises(error_type):
        SpotifyClient(auth_store=auth_store, transport=transport).request("PUT", "/me/player/pause")


def test_404_no_active_device_maps_to_domain_error(auth_store):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            404,
            json={
                "error": {
                    "status": 404,
                    "message": "Player command failed: No active device found",
                    "reason": "NO_ACTIVE_DEVICE",
                }
            },
        )
    )

    with pytest.raises(SpotifyNoActiveDevice):
        SpotifyClient(auth_store=auth_store, transport=transport).request("POST", "/me/player/next")


def test_get_player_normalizes_track_and_device(auth_store):
    payload = {
        "is_playing": True,
        "progress_ms": 1200,
        "shuffle_state": True,
        "repeat_state": "context",
        "device": {"id": "device-1", "name": "Office", "volume_percent": 35},
        "item": {
            "id": "track-1",
            "uri": "spotify:track:track-1",
            "name": "So What",
            "duration_ms": 545000,
            "artists": [{"name": "Miles Davis"}],
            "album": {"name": "Kind of Blue", "images": [{"url": "https://img/cover.jpg"}]},
        },
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    result = SpotifyClient(auth_store=auth_store, transport=transport).get_player()

    assert result == {
        "is_playing": True,
        "progress_ms": 1200,
        "duration_ms": 545000,
        "track": {"id": "track-1", "uri": "spotify:track:track-1", "name": "So What"},
        "artists": ["Miles Davis"],
        "album": "Kind of Blue",
        "artwork_url": "https://img/cover.jpg",
        "device": {"id": "device-1", "name": "Office", "volume_percent": 35},
        "shuffle": True,
        "repeat": "context",
    }


def test_episode_player_state_requests_and_displays_podcast_metadata(auth_store):
    def handle(request):
        assert request.url.params["additional_types"] == "track,episode"
        return httpx.Response(200, json={"is_playing":True, "item":{"id":"ep1", "uri":"spotify:episode:ep1", "type":"episode", "name":"Travel", "images":[{"url":"https://img/episode"}], "show":{"name":"WTF is with Nikhil Kamath", "publisher":"Nikhil Kamath"}}})
    result = SpotifyClient(auth_store, transport=httpx.MockTransport(handle)).get_player()
    assert result["artists"] == ["WTF is with Nikhil Kamath"]
    assert result["artwork_url"] == "https://img/episode"


def test_raw_spotify_error_body_never_appears_in_exception(auth_store):
    secret = "refresh_token=super-secret-value"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, text=secret)
    )

    with pytest.raises(Exception) as caught:
        SpotifyClient(auth_store=auth_store, transport=transport).request("GET", "/me/player")

    assert "super-secret-value" not in str(caught.value)
    assert secret not in repr(caught.value)


def test_linked_playlist_metadata_is_exact_public_and_survives_refresh(auth_store):
    def handler(request):
        if request.url.path == '/v1/me':
            return httpx.Response(200,json={'id':'account-a'})
        if request.url.path.startswith('/v1/playlists/'):
            return httpx.Response(403,json={'error':{'message':'restricted'}})
        if request.url.path == '/oembed':
            assert 'authorization' not in request.headers
            assert request.url.params['url'] == 'https://open.spotify.com/playlist/Mix'
            return httpx.Response(200,json={'title':'Daily Mix 1','thumbnail_url':'https://i.scdn.co/image/cover'})
        if request.url.path == '/api/token':
            return httpx.Response(200,json={'access_token':'new','expires_in':3600})
        raise AssertionError(request.url)
    client=SpotifyClient(auth_store,transport=httpx.MockTransport(handler))
    result=client.remember_playlist_links(['spotify:playlist:Mix','spotify:playlist:Mix'])
    assert result['total'] == 1 and result['items'][0]['name'] == 'Daily Mix 1'
    assert result['items'][0]['uri'] == 'spotify:playlist:Mix'
    client.refresh()
    assert SpotifyClient(SpotifyAuthStore(auth_store.root)).get_linked_playlists()[0]['id'] == 'Mix'
    # Reauthorizing replaces the connection; no references leak to a new account.
    auth_store.save_tokens({'access_token':'other','refresh_token':'other'})
    assert client.get_linked_playlists() == []


def test_unavailable_public_metadata_keeps_honest_exact_reference(auth_store):
    def handler(request):
        if request.url.path == '/v1/me': return httpx.Response(200,json={'id':'account'})
        return httpx.Response(404,json={'error':{'message':'not found'}})
    client=SpotifyClient(auth_store,transport=httpx.MockTransport(handler))
    row=client.remember_playlist_links(['spotify:playlist:Unknown'])['items'][0]
    assert row['name'].startswith('Linked playlist ') and row['uri'] == 'spotify:playlist:Unknown'
    assert row['images'] == []
    assert 'metadata_source' not in row
    labelled=client.remember_playlist_links(['spotify:playlist:Unknown'],labels={'spotify:playlist:Unknown':'Your Top Songs 2022'})['items'][0]
    assert labelled['name']=='Your Top Songs 2022' and labelled['metadata_source']=='provided_label'


def test_link_import_validates_all_urls_before_any_network_or_storage(auth_store):
    from plugins.connectors.spotify.errors import SpotifyAPIError
    client=SpotifyClient(auth_store,transport=httpx.MockTransport(lambda request: pytest.fail('No network')))
    with pytest.raises(SpotifyAPIError):
        client.remember_playlist_links(['spotify:playlist:Valid','https://untrusted.test/private'])
    assert client.get_linked_playlists() == []


def test_unexposed_resource_404_has_distinct_safe_code(auth_store):
    from plugins.connectors.spotify.errors import SpotifyResourceUnavailable
    client=SpotifyClient(auth_store,transport=httpx.MockTransport(lambda request:httpx.Response(404,json={'error':{'message':'hidden provider detail'}})))
    with pytest.raises(SpotifyResourceUnavailable) as exc:client.request('GET','/playlists/Mix/items')
    assert exc.value.code=='resource_unavailable' and 'hidden provider detail' not in str(exc.value)
