"""Smoke test for GET /api/mcp/health."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent import api as api_mod


@pytest.fixture
def client(monkeypatch):
    def _fake_vector():
        return {"ok": True, "mode": "embedded-chroma", "location": "/tmp/chroma", "collections": []}

    monkeypatch.setattr(api_mod, "_vector_health", _fake_vector)
    return TestClient(api_mod.app)


def test_mcp_health_returns_all_servers(client: TestClient) -> None:
    r = client.get("/api/mcp/health")
    assert r.status_code == 200
    body = r.json()
    servers = {s["name"] for s in body["mcp_servers"]}
    assert servers == {
        "filesystem", "apify", "playwright", "github",
        "obsidian", "context7", "gitmcp", "context_mode",
    }


def test_mcp_health_each_server_has_required_keys(client: TestClient) -> None:
    body = client.get("/api/mcp/health").json()
    for entry in body["mcp_servers"]:
        assert "name" in entry
        assert "configured" in entry  # bool
        assert "endpoint" in entry
        assert "notes" in entry
        assert isinstance(entry["configured"], bool)


def test_mcp_health_includes_adjacent_services(client: TestClient) -> None:
    body = client.get("/api/mcp/health").json()
    assert "vector" in body
    assert "honcho" in body
    assert "reachable" in body["honcho"]
    assert "base_url" in body["honcho"]
