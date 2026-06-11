from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from agent import api
from agent.coding.models import AccessMode, CodingEvent, ProviderHealth, ProviderName, utc_now
from agent.coding.service import CodingServiceError


class FakeCodingService:
    def health(self):
        return [
            ProviderHealth(ProviderName.codex, True, True, "Codex ready."),
            ProviderHealth(ProviderName.claude, False, False, "Claude Agent SDK is not installed."),
        ]

    async def create_session(self, request):
        return type(
            "Session",
            (),
            {
                "id": "code_1",
                "provider": ProviderName.codex,
                "provider_session_id": "thread_1",
                "cwd": request.resolved_cwd(),
                "access_mode": request.access_mode,
                "title": request.title or "repo",
                "status": "idle",
                "created_at": "2026-06-05T00:00:00+00:00",
                "updated_at": "2026-06-05T00:00:00+00:00",
            },
        )()

    def list_sessions(self):
        return []

    def get_session(self, session_id):
        return type(
            "Session",
            (),
            {
                "id": session_id,
                "provider": ProviderName.codex,
                "provider_session_id": "thread_1",
                "cwd": "D:\\Vellum",
                "access_mode": AccessMode.read_only,
                "title": "repo",
                "status": "idle",
                "created_at": "2026-06-05T00:00:00+00:00",
                "updated_at": "2026-06-05T00:00:00+00:00",
            },
        )()

    async def run_turn(self, session_id: str, prompt: str) -> AsyncIterator[CodingEvent]:
        yield CodingEvent(
            "evt_1",
            session_id,
            "turn_1",
            ProviderName.codex,
            "assistant.final",
            "done",
            {"text": prompt},
            utc_now(),
        )

    def list_events(self, session_id):
        return []

    async def stop_turn(self, session_id: str):
        return None


class MissingSessionCodingService(FakeCodingService):
    def get_session(self, session_id):
        raise CodingServiceError("Coding session not found.")

    async def run_turn(self, session_id: str, prompt: str) -> AsyncIterator[CodingEvent]:
        raise CodingServiceError("Coding session not found.")
        yield

    async def stop_turn(self, session_id: str):
        raise CodingServiceError("Coding session not found.")


class RunningSessionCodingService(FakeCodingService):
    def get_session(self, session_id):
        return type(
            "Session",
            (),
            {
                "id": session_id,
                "provider": ProviderName.codex,
                "provider_session_id": "thread_1",
                "cwd": "D:\\Vellum",
                "access_mode": AccessMode.read_only,
                "title": "repo",
                "status": "running",
                "created_at": "2026-06-05T00:00:00+00:00",
                "updated_at": "2026-06-05T00:00:00+00:00",
            },
        )()


def test_coding_health_endpoint(monkeypatch):
    monkeypatch.setattr(api, "coding_service", FakeCodingService())

    with TestClient(api.app) as client:
        response = client.get("/api/coding/health")

    assert response.status_code == 200
    assert response.json()["providers"][0]["provider"] == "codex"
    assert response.json()["providers"][1]["available"] is False


def test_coding_session_create_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "coding_service", FakeCodingService())

    with TestClient(api.app) as client:
        response = client.post(
            "/api/coding/sessions",
            json={"provider": "codex", "cwd": str(tmp_path), "access_mode": "read_only", "title": "repo"},
        )

    assert response.status_code == 200
    assert response.json()["id"] == "code_1"
    assert response.json()["provider_session_id"] == "thread_1"


def test_coding_turn_stream_endpoint(monkeypatch):
    monkeypatch.setattr(api, "coding_service", FakeCodingService())

    with TestClient(api.app) as client:
        with client.stream("POST", "/api/coding/sessions/code_1/turns/stream", json={"prompt": "hello"}) as response:
            body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert "event: assistant_final" in body
    assert '"text": "hello"' in body


def test_coding_turn_stream_missing_session_returns_404(monkeypatch):
    monkeypatch.setattr(api, "coding_service", MissingSessionCodingService())

    with TestClient(api.app) as client:
        response = client.post("/api/coding/sessions/missing/turns/stream", json={"prompt": "hello"})

    assert response.status_code == 404


def test_coding_turn_stream_running_session_returns_409(monkeypatch):
    monkeypatch.setattr(api, "coding_service", RunningSessionCodingService())

    with TestClient(api.app) as client:
        response = client.post("/api/coding/sessions/code_1/turns/stream", json={"prompt": "hello"})

    assert response.status_code == 409


def test_coding_stop_missing_session_returns_404(monkeypatch):
    monkeypatch.setattr(api, "coding_service", MissingSessionCodingService())

    with TestClient(api.app) as client:
        response = client.post("/api/coding/sessions/missing/stop")

    assert response.status_code == 404
