import time

import httpx
import pytest

from plugins.connectors.spotify.auth import SpotifyAuthStore
from plugins.connectors.spotify.client import SpotifyClient
from plugins.connectors.spotify.errors import (
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


def test_204_is_inactive_state(auth_store):
    transport = httpx.MockTransport(lambda request: httpx.Response(204))

    result = SpotifyClient(auth_store=auth_store, transport=transport).request(
        "GET", "/me/player/currently-playing"
    )

    assert result == {"is_playing": False, "item": None}


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


def test_raw_spotify_error_body_never_appears_in_exception(auth_store):
    secret = "refresh_token=super-secret-value"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, text=secret)
    )

    with pytest.raises(Exception) as caught:
        SpotifyClient(auth_store=auth_store, transport=transport).request("GET", "/me/player")

    assert "super-secret-value" not in str(caught.value)
    assert secret not in repr(caught.value)
