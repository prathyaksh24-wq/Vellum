from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agent.plugins import google_calendar_api


def build_client() -> TestClient:
    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(google_calendar_api.router)
    app.include_router(api)
    return TestClient(app)


class FakeStore:
    def __init__(self) -> None:
        self.flow = None
        self.profile = None

    def save_flow(self, flow):
        self.flow = dict(flow)

    def consume_flow(self, state):
        assert state == "calendar.state-value"
        return {"redirect_uri": google_calendar_api.GOOGLE_CALENDAR_REDIRECT_URI, "code_verifier": "verifier"}

    def save_profile(self, profile):
        self.profile = dict(profile)


class FakeClient:
    def __init__(self) -> None:
        self.exchange = None

    def exchange_code(self, **kwargs):
        self.exchange = dict(kwargs)

    def primary_calendar(self):
        return {"id": "private-account", "summary": "Primary", "timeZone": "Asia/Kolkata"}

    def calendar_settings(self):
        return {"timezone": "Asia/Kolkata", "weekStart": "1"}


class FakeService:
    def calendars(self, _payload):
        return {"action": "calendar.calendars", "items": [{"id": "primary", "summary": "Primary"}]}

    def create_event(self, payload):
        if payload.get("confirm") is not True:
            raise google_calendar_api.ToolPermissionError("confirmation required")
        return {"action": "calendar.create_event", "event": {"id": "event-1", "summary": payload["summary"]}}


def test_oauth_start_reuses_existing_google_client_without_exposing_secret(monkeypatch) -> None:
    store = FakeStore()
    settings = type("Settings", (), {
        "google_calendar_oauth_client_id": "",
        "youtube_oauth_client_id": "shared-client",
    })()
    monkeypatch.setattr(google_calendar_api, "get_settings", lambda: settings)
    monkeypatch.setattr(google_calendar_api, "google_calendar_store", lambda: store)
    monkeypatch.setattr(google_calendar_api, "google_calendar_pkce_pair", lambda: ("verifier", "challenge"))
    monkeypatch.setattr(google_calendar_api.secrets, "token_urlsafe", lambda _length: "state-value")
    monkeypatch.setattr(
        google_calendar_api,
        "google_calendar_authorization_url",
        lambda **kwargs: "https://accounts.google.test/auth?client_id=" + kwargs["client_id"],
    )

    response = build_client().post("/api/plugins/google-calendar/oauth/start")

    assert response.status_code == 200
    assert response.json()["authorization_url"].endswith("client_id=shared-client")
    assert store.flow["state"] == "calendar.state-value"
    assert "secret" not in response.text.casefold()


def test_oauth_callback_saves_primary_calendar_metadata(monkeypatch) -> None:
    store = FakeStore()
    client = FakeClient()
    monkeypatch.setattr(google_calendar_api, "google_calendar_store", lambda: store)
    monkeypatch.setattr(google_calendar_api, "google_calendar_client", lambda **_kwargs: client)

    response = build_client().get(
        "/api/plugins/google-calendar/oauth/callback",
        params={"code": "authorization-code", "state": "calendar.state-value"},
    )

    assert response.status_code == 200
    assert "Google Calendar OAuth complete" in response.text
    assert store.profile["timeZone"] == "Asia/Kolkata"
    assert client.exchange["code"] == "authorization-code"


def test_api_reads_and_confirmation_gates_writes(monkeypatch) -> None:
    monkeypatch.setattr(google_calendar_api, "google_calendar_service", lambda: FakeService())
    client = build_client()

    calendars = client.get("/api/plugins/google-calendar/calendars")
    blocked = client.post("/api/plugins/google-calendar/events", json={
        "summary": "Review",
        "start": "2026-09-10T10:00:00Z",
        "end": "2026-09-10T11:00:00Z",
        "confirm": False,
    })
    created = client.post("/api/plugins/google-calendar/events", json={
        "summary": "Review",
        "start": "2026-09-10T10:00:00Z",
        "end": "2026-09-10T11:00:00Z",
        "confirm": True,
    })

    assert calendars.status_code == 200
    assert blocked.status_code == 403
    assert created.status_code == 200
    assert created.json()["event"]["id"] == "event-1"
