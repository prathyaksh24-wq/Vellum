import json
import time
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
import pytest

from agent import api
from plugins.connectors.spotify.auth import SpotifyAuthStore


@pytest.fixture(autouse=True)
def disable_runtime_services(monkeypatch):
    monkeypatch.setattr(api, "start_scheduler", lambda: None)
    monkeypatch.setattr(api, "start_vault_watcher", lambda: None)


class FakeSpotifyClient:
    def __init__(self, store):
        self.store = store
        self.calls = []

    def exchange_code(self, **kwargs):
        self.calls.append(("exchange_code", kwargs))
        saved = {
            "client_id": kwargs["client_id"],
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_at": time.time() + 3600,
            "scope": "user-read-private user-read-playback-state",
        }
        self.store.save_tokens(saved)
        return saved

    def get_profile(self):
        return {"id": "user-1", "display_name": "Listener", "product": "premium"}

    def get_player(self):
        return {"is_playing": False, "track": None, "device": None}

    def get_devices(self):
        return {"devices": [{"id": "device-1", "name": "Office"}]}

    def get_queue(self):
        return {"queue": [{"uri": "spotify:track:1", "name": "Blue in Green"}]}

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return {}


@pytest.fixture
def spotify_backend(monkeypatch, tmp_path):
    store = SpotifyAuthStore(tmp_path / "spotify")
    client = FakeSpotifyClient(store)
    invalidations = []
    monkeypatch.setattr(api, "_spotify_store", lambda: store)
    monkeypatch.setattr(api, "_spotify_client", lambda: client)
    monkeypatch.setattr(api.agent, "invalidate", lambda: invalidations.append(True))
    return store, client, invalidations


def test_spotify_oauth_start_creates_pkce_flow(spotify_backend):
    store, _client, _invalidations = spotify_backend

    with TestClient(api.app) as client:
        response = client.post("/api/plugins/spotify/oauth/start", json={"client_id": "client-123"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["redirect_uri"] == api.SPOTIFY_REDIRECT_URI
    query = parse_qs(urlparse(payload["authorization_url"]).query)
    assert query["client_id"] == ["client-123"]
    flow = json.loads(store.flow_path.read_text(encoding="utf-8"))
    assert flow["state"] == query["state"][0]
    assert flow["client_id"] == "client-123"
    assert flow["code_verifier"]


def test_spotify_callback_exchanges_code_and_invalidates_agent(spotify_backend):
    store, spotify, invalidations = spotify_backend
    store.save_flow(
        {
            "state": "state-1",
            "code_verifier": "verifier-1",
            "client_id": "client-123",
            "redirect_uri": api.SPOTIFY_REDIRECT_URI,
            "created_at": time.time(),
        }
    )

    with TestClient(api.app) as client:
        response = client.get(
            "/api/plugins/spotify/oauth/callback?code=code-1&state=state-1"
        )

    assert response.status_code == 200
    assert "Spotify connected" in response.text
    assert spotify.calls[0][0] == "exchange_code"
    assert store.load_tokens()["refresh_token"] == "refresh-secret"
    assert invalidations == [True]


def test_spotify_callback_rejects_state_mismatch(spotify_backend):
    store, _spotify, _invalidations = spotify_backend
    store.save_flow(
        {"state": "expected", "code_verifier": "v", "created_at": time.time()}
    )

    with TestClient(api.app) as client:
        response = client.get(
            "/api/plugins/spotify/oauth/callback?code=code-1&state=wrong"
        )

    assert response.status_code == 400
    assert "state" in response.text.lower()


def test_spotify_status_never_returns_credentials(spotify_backend):
    store, _spotify, _invalidations = spotify_backend
    store.save_tokens(
        {
            "client_id": "client-secret-value",
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_at": time.time() + 3600,
            "scope": "user-read-private user-read-playback-state",
        }
    )

    with TestClient(api.app) as client:
        response = client.get("/api/plugins/spotify/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is True
    assert payload["account_name"] == "Listener"
    assert payload["product"] == "premium"
    serialized = json.dumps(payload).lower()
    assert "access-secret" not in serialized
    assert "refresh-secret" not in serialized
    assert "client-secret-value" not in serialized


def test_spotify_player_and_allowlisted_action_share_service(spotify_backend):
    store, spotify, _invalidations = spotify_backend
    store.save_tokens(
        {"client_id": "c", "access_token": "a", "refresh_token": "r", "expires_at": time.time() + 3600}
    )

    with TestClient(api.app) as client:
        player = client.get("/api/plugins/spotify/player")
        action = client.post(
            "/api/plugins/spotify/player/action",
            json={"action": "pause"},
        )
        invalid = client.post(
            "/api/plugins/spotify/player/action",
            json={"action": "delete_playlist"},
        )

    assert player.status_code == 200
    assert player.json()["is_playing"] is False
    assert action.status_code == 200
    assert spotify.calls[-1][:2] == ("PUT", "/me/player/pause")
    assert invalid.status_code == 422


def test_spotify_player_details_include_devices_and_queue(spotify_backend):
    store, _spotify, _invalidations = spotify_backend
    store.save_tokens(
        {"client_id": "c", "access_token": "a", "refresh_token": "r", "expires_at": time.time() + 3600}
    )

    with TestClient(api.app) as client:
        response = client.get("/api/plugins/spotify/player?details=true")

    assert response.status_code == 200
    assert response.json()["devices"] == [{"id": "device-1", "name": "Office"}]
    assert response.json()["queue"] == [{"uri": "spotify:track:1", "name": "Blue in Green"}]


def test_spotify_logout_removes_credentials_and_invalidates(spotify_backend):
    store, _spotify, invalidations = spotify_backend
    store.save_tokens(
        {"client_id": "c", "access_token": "a", "refresh_token": "r", "expires_at": time.time() + 3600}
    )

    with TestClient(api.app) as client:
        response = client.post("/api/plugins/spotify/logout")

    assert response.status_code == 200
    assert not store.auth_path.exists()
    assert invalidations == [True]


def test_plugins_catalog_includes_spotify(monkeypatch):
    monkeypatch.setattr(api, "mcp_health", lambda probe=False: {"mcp_servers": []})

    with TestClient(api.app) as client:
        response = client.get("/api/plugins")

    spotify = next(item for item in response.json()["plugins"] if item["id"] == "spotify")
    assert spotify["metadata"]["portable_plugin"]["capabilities"] == [
        "spotify.playback",
        "spotify.devices",
        "spotify.queue",
        "spotify.search",
        "spotify.playlists",
        "spotify.albums",
        "spotify.library",
    ]
