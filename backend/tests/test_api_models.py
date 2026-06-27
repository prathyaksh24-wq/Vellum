"""Smoke tests for GET /api/models and POST /api/settings/active-model."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent import api as api_mod
from agent.llm import providers as providers_mod


@pytest.fixture(autouse=True)
def _reset_registry():
    """The provider registry is cached via lru_cache; reset between tests
    so changes don't leak between cases."""
    providers_mod.get_provider_registry.cache_clear()
    yield
    providers_mod.get_provider_registry.cache_clear()


@pytest.fixture
def client(monkeypatch):
    # Prevent the real LazyAgent from being touched: stub aclose so the
    # active-model switch doesn't try to close a real async sqlite handle.
    async def fake_aclose():
        return None

    monkeypatch.setattr(api_mod.agent, "aclose", fake_aclose)
    return TestClient(api_mod.app)


def test_list_models_returns_catalog(client: TestClient) -> None:
    r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert "active" in body and "groups" in body and "models" in body
    ids = {m["id"] for m in body["models"]}
    # User's wanted models are present
    assert "google/gemma-4-31b-it" in ids
    assert "anthropic/claude-opus-4.7" in ids
    assert "openai/gpt-5.5" in ids
    assert "moonshotai/kimi-k2.6" in ids


def test_set_active_model_by_id(client: TestClient) -> None:
    r = client.post("/api/settings/active-model", json={"model": "openai/gpt-5.5"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == "openai/gpt-5.5"
    assert body["provider"] == "openai"
    assert body["open_weights"] is False
    # Verify it stuck on the registry
    assert providers_mod.get_provider_registry().current_model().id == "openai/gpt-5.5"


def test_set_active_model_by_label(client: TestClient) -> None:
    r = client.post("/api/settings/active-model", json={"model": "Kimi K2.6"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "moonshotai/kimi-k2.6"


def test_set_active_model_unknown_returns_400(client: TestClient) -> None:
    r = client.post("/api/settings/active-model", json={"model": "nope/nothing"})
    assert r.status_code == 400


def test_set_active_model_returns_active_on_models_endpoint(client: TestClient) -> None:
    client.post("/api/settings/active-model", json={"model": "deepseek/deepseek-v4-flash"})
    body = client.get("/api/models").json()
    assert body["active"]["id"] == "deepseek/deepseek-v4-flash"
