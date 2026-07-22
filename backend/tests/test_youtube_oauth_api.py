from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agent.plugins import youtube_api


def build_client() -> TestClient:
    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(youtube_api.router)
    app.include_router(api)
    return TestClient(app)


class FakeStore:
    def __init__(self) -> None:
        self.flow = None
        self.profile = None

    def save_flow(self, flow: dict) -> None:
        self.flow = dict(flow)

    def consume_flow(self, state: str) -> dict:
        assert state == "state-value"
        return {
            "redirect_uri": youtube_api.YOUTUBE_REDIRECT_URI,
            "code_verifier": "verifier-value",
        }

    def save_profile(self, profile: dict) -> None:
        self.profile = dict(profile)


class FakeYouTubeClient:
    def __init__(self) -> None:
        self.exchange = None
        self.disconnected = False

    def exchange_code(self, **kwargs) -> None:
        self.exchange = dict(kwargs)

    def get_my_channel(self) -> dict:
        return {"channel_id": "UC-primary", "title": "Primary channel"}

    def disconnect(self) -> None:
        self.disconnected = True


def test_youtube_oauth_start_uses_backend_credentials_without_exposing_secret(monkeypatch) -> None:
    store = FakeStore()
    monkeypatch.setattr(
        youtube_api,
        "get_settings",
        lambda: type("Settings", (), {"youtube_oauth_client_id": "client-id"})(),
    )
    monkeypatch.setattr(youtube_api, "youtube_store", lambda: store)
    monkeypatch.setattr(youtube_api, "youtube_pkce_pair", lambda: ("verifier-value", "challenge-value"))
    monkeypatch.setattr(youtube_api.secrets, "token_urlsafe", lambda _length: "state-value")
    monkeypatch.setattr(
        youtube_api,
        "youtube_authorization_url",
        lambda **kwargs: "https://accounts.google.test/auth?client_id=" + kwargs["client_id"],
    )

    response = build_client().post("/api/plugins/youtube/oauth/start")

    assert response.status_code == 200
    assert response.json()["authorization_url"].endswith("client_id=client-id")
    assert response.json()["scopes"] == ["https://www.googleapis.com/auth/youtube.readonly"]
    assert "secret" not in response.text.casefold()
    assert store.flow["code_verifier"] == "verifier-value"


def test_youtube_oauth_callback_saves_channel_profile(monkeypatch) -> None:
    store = FakeStore()
    client = FakeYouTubeClient()
    monkeypatch.setattr(youtube_api, "youtube_store", lambda: store)
    monkeypatch.setattr(youtube_api, "youtube_client", lambda **_kwargs: client)

    response = build_client().get(
        "/api/plugins/youtube/oauth/callback",
        params={"code": "authorization-code", "state": "state-value"},
    )

    assert response.status_code == 200
    assert "YouTube OAuth complete" in response.text
    assert client.exchange == {
        "code": "authorization-code",
        "redirect_uri": youtube_api.YOUTUBE_REDIRECT_URI,
        "code_verifier": "verifier-value",
    }
    assert store.profile["channel_id"] == "UC-primary"


def test_youtube_sync_requires_connection(monkeypatch) -> None:
    monkeypatch.setattr(
        youtube_api,
        "youtube_status",
        lambda: {"configured": True, "connected": False, "status": "not_connected"},
    )

    response = build_client().post("/api/plugins/youtube/sync", json={})

    assert response.status_code == 409


def test_youtube_sync_forwards_explicit_idempotency_key(monkeypatch) -> None:
    observed = {}

    class FakeSync:
        def run(self, **kwargs):
            observed.update(kwargs)
            return {"status": "completed", "stats": {"subscriptions": 3}}

    monkeypatch.setattr(
        youtube_api,
        "youtube_status",
        lambda: {"configured": True, "connected": True, "status": "ready"},
    )
    monkeypatch.setattr(youtube_api, "YouTubeKnowledgeSync", FakeSync)

    response = build_client().post(
        "/api/plugins/youtube/sync",
        json={"idempotency_key": "manual-test-run"},
    )

    assert response.status_code == 200
    assert response.json()["stats"]["subscriptions"] == 3
    assert observed == {"idempotency_key": "manual-test-run", "requested_by": "user"}


def test_youtube_disconnect_revokes_tokens(monkeypatch) -> None:
    client = FakeYouTubeClient()
    monkeypatch.setattr(youtube_api, "youtube_client", lambda: client)

    response = build_client().delete("/api/plugins/youtube/connection")

    assert response.status_code == 200
    assert response.json() == {"disconnected": True}
    assert client.disconnected is True
