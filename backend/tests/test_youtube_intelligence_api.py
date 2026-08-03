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


def test_youtube_intelligence_status_exposes_backfill_readiness(monkeypatch) -> None:
    class FakeIntelligence:
        def __init__(self, store):
            assert store == "knowledge-store"

        def status(self):
            return {
                "local_only": True,
                "ready": False,
                "phase": "backfill_required",
                "projection_ready": False,
                "identity_ready": False,
            }

    monkeypatch.setattr(youtube_api, "get_knowledge_core", lambda: SimpleNamespace(store="knowledge-store"))
    monkeypatch.setattr(youtube_api, "YouTubeIntelligenceService", FakeIntelligence)

    response = _client().get("/api/plugins/youtube/intelligence/status")

    assert response.status_code == 200
    assert response.json()["phase"] == "backfill_required"
    assert response.json()["identity_ready"] is False


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


def test_youtube_identity_api_returns_local_review_candidates(monkeypatch) -> None:
    class FakeIdentityService:
        def __init__(self, store):
            assert store == "knowledge-store"

        def profile(self, *, limit):
            assert limit == 25
            return {
                "local_only": True,
                "counts": {
                    "entities": 2,
                    "aliases": 2,
                    "collision_candidates": 1,
                },
                "candidates": [
                    {
                        "candidate_id": "ytcol-example",
                        "alias": "Shared Name",
                        "external_ids": ["UC-one", "UC-two"],
                        "entity_ids": ["ent-one", "ent-two"],
                        "reason": "shared_alias_distinct_external_ids",
                        "requires_review": True,
                        "auto_merge": False,
                    }
                ],
            }

    monkeypatch.setattr(youtube_api, "get_knowledge_core", lambda: SimpleNamespace(store="knowledge-store"))
    monkeypatch.setattr(youtube_api, "YouTubeChannelIdentityService", FakeIdentityService, raising=False)

    response = _client().get(
        "/api/plugins/youtube/intelligence/identities",
        params={"limit": 25},
    )

    assert response.status_code == 200
    assert response.json()["local_only"] is True
    assert response.json()["candidates"][0]["auto_merge"] is False
