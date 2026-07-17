from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from agent import api
from agent.coding.adapters.base import CodingAdapterError
from agent.coding.models import AccessMode, CodingEvent, ProviderHealth, ProviderName, utc_now
from agent.coding.service import CodingServiceError


class FakeCodingService:
    def __init__(self):
        self.last_limits = None
        self.last_after_sequence = None

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

    async def run_turn(self, session_id: str, prompt: str, *, limits=None) -> AsyncIterator[CodingEvent]:
        self.last_limits = limits
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

    def list_events(self, session_id, *, after_sequence=0):
        self.last_after_sequence = after_sequence
        return []

    async def stop_turn(self, session_id: str):
        return None


class MissingSessionCodingService(FakeCodingService):
    def get_session(self, session_id):
        raise CodingServiceError("Coding session not found.")

    async def run_turn(self, session_id: str, prompt: str, *, limits=None) -> AsyncIterator[CodingEvent]:
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


class FailingCreateCodingService(FakeCodingService):
    async def create_session(self, request):
        raise CodingServiceError("Coding session failed to start.") from CodingAdapterError(
            "Codex SDK is not installed."
        )


class UnavailableProviderCodingService(FakeCodingService):
    def health(self):
        return [ProviderHealth(ProviderName.codex, False, False, "Codex SDK is not installed.")]


class UnavailableCreateWouldSucceedCodingService(FakeCodingService):
    def health(self):
        return [ProviderHealth(ProviderName.claude, False, False, "Claude Agent SDK is not installed.")]


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


def test_coding_session_create_provider_unavailable_returns_503(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "coding_service", FailingCreateCodingService())

    with TestClient(api.app) as client:
        response = client.post(
            "/api/coding/sessions",
            json={"provider": "codex", "cwd": str(tmp_path), "access_mode": "read_only"},
        )

    assert response.status_code == 503


def test_coding_session_create_preflights_unavailable_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "coding_service", UnavailableCreateWouldSucceedCodingService())

    with TestClient(api.app) as client:
        response = client.post(
            "/api/coding/sessions",
            json={"provider": "claude", "cwd": str(tmp_path), "access_mode": "read_only"},
        )

    assert response.status_code == 503


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


def test_coding_turn_stream_provider_unavailable_returns_503(monkeypatch):
    monkeypatch.setattr(api, "coding_service", UnavailableProviderCodingService())

    with TestClient(api.app) as client:
        response = client.post("/api/coding/sessions/code_1/turns/stream", json={"prompt": "hello"})

    assert response.status_code == 503


def test_coding_stop_missing_session_returns_404(monkeypatch):
    monkeypatch.setattr(api, "coding_service", MissingSessionCodingService())

    with TestClient(api.app) as client:
        response = client.post("/api/coding/sessions/missing/stop")

    assert response.status_code == 404


def test_coding_turn_stream_passes_bounded_run_limits(monkeypatch):
    service = FakeCodingService()
    monkeypatch.setattr(api, "coding_service", service)

    with TestClient(api.app) as client:
        response = client.post(
            "/api/coding/sessions/code_1/turns/stream",
            json={"prompt": "hello", "max_runtime_seconds": 45, "max_provider_events": 250},
        )

    assert response.status_code == 200
    assert service.last_limits.max_runtime_seconds == 45
    assert service.last_limits.max_provider_events == 250


def test_coding_turn_stream_rejects_invalid_run_limits(monkeypatch):
    monkeypatch.setattr(api, "coding_service", FakeCodingService())

    with TestClient(api.app) as client:
        response = client.post(
            "/api/coding/sessions/code_1/turns/stream",
            json={"prompt": "hello", "max_runtime_seconds": 0, "max_provider_events": 0},
        )

    assert response.status_code == 422


def test_coding_event_replay_passes_sequence_cursor(monkeypatch):
    service = FakeCodingService()
    monkeypatch.setattr(api, "coding_service", service)

    with TestClient(api.app) as client:
        response = client.get("/api/coding/sessions/code_1/events?after_sequence=17")

    assert response.status_code == 200
    assert service.last_after_sequence == 17


def test_coding_project_file_returns_bounded_workspace_text(monkeypatch, tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "app.py").write_text("print('vellum')\n", encoding="utf-8")
    monkeypatch.setattr(api, "_coding_project_roots", lambda: [tmp_path.resolve()])

    with TestClient(api.app) as client:
        response = client.get(
            "/api/coding/projects/file",
            params={"root": str(tmp_path), "path": "src/app.py"},
        )

    assert response.status_code == 200
    assert response.json()["path"] == "src/app.py"
    assert response.json()["content"].replace("\r\n", "\n") == "print('vellum')\n"
    assert response.json()["truncated"] is False


def test_coding_project_file_rejects_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_coding_project_roots", lambda: [tmp_path.resolve()])

    with TestClient(api.app) as client:
        response = client.get(
            "/api/coding/projects/file",
            params={"root": str(tmp_path), "path": "../outside.txt"},
        )

    assert response.status_code == 400


def test_coding_project_file_blocks_protected_files(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("SECRET=value\n", encoding="utf-8")
    monkeypatch.setattr(api, "_coding_project_roots", lambda: [tmp_path.resolve()])

    with TestClient(api.app) as client:
        response = client.get(
            "/api/coding/projects/file",
            params={"root": str(tmp_path), "path": ".env"},
        )

    assert response.status_code == 403
    assert "SECRET" not in response.text


def test_coding_project_file_truncates_large_files(monkeypatch, tmp_path):
    (tmp_path / "large.txt").write_text("x" * (512 * 1024 + 20), encoding="utf-8")
    monkeypatch.setattr(api, "_coding_project_roots", lambda: [tmp_path.resolve()])

    with TestClient(api.app) as client:
        response = client.get(
            "/api/coding/projects/file",
            params={"root": str(tmp_path), "path": "large.txt"},
        )

    assert response.status_code == 200
    assert len(response.json()["content"]) == 512 * 1024
    assert response.json()["truncated"] is True
