from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agent.plugins import youtube_api


def _client() -> TestClient:
    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(youtube_api.router)
    app.include_router(api)
    return TestClient(app)


def test_youtube_intelligence_api_returns_local_snapshot(monkeypatch) -> None:
    class FakeIntelligence:
        def __init__(self, store):
            assert store == "knowledge-store"

        def snapshot(self, *, limit, query):
            assert query == ""
            return {
                "local_only": True,
                "channels": [{"label": "Sidemen", "trend": "falling"}][:limit],
                "search_themes": [],
            }

    monkeypatch.setattr(youtube_api, "get_knowledge_core", lambda: SimpleNamespace(store="knowledge-store"))
    monkeypatch.setattr(youtube_api, "YouTubeIntelligenceService", FakeIntelligence)

    response = _client().get("/api/plugins/youtube/intelligence", params={"limit": 5})

    assert response.status_code == 200
    assert response.json()["local_only"] is True
    assert response.json()["channels"][0] == {"label": "Sidemen", "trend": "falling"}


def test_youtube_intelligence_api_rebuilds_only_derived_state(monkeypatch) -> None:
    class FakeIntelligence:
        def __init__(self, store):
            assert store == "knowledge-store"

        def rebuild(self):
            return {
                "observations_scanned": 100,
                "signals_created": 10,
                "signals_existing": 90,
                "subjects_recomputed": 4,
            }

    monkeypatch.setattr(youtube_api, "get_knowledge_core", lambda: SimpleNamespace(store="knowledge-store"))
    monkeypatch.setattr(youtube_api, "YouTubeIntelligenceService", FakeIntelligence)

    response = _client().post("/api/plugins/youtube/intelligence/rebuild")

    assert response.status_code == 200
    assert response.json()["subjects_recomputed"] == 4
