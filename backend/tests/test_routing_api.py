from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.app_actions.settings_runtime import SettingsRuntimeActionService
from agent.llm.routing import api as routing_api
from agent.llm.routing.api import router
from agent.llm.routing.pool import CredentialPool
from agent.llm.routing.secrets import SecretResolver
from agent.llm.routing.store import RoutingStore


class FakeKeyring:
    def __init__(self) -> None:
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


def make_client(monkeypatch, tmp_path) -> TestClient:
    store = RoutingStore(tmp_path / "routing.db")
    secrets = SecretResolver(
        store,
        FakeKeyring(),
        fingerprint_salt=b"test-salt",
    )
    runtime = SimpleNamespace(
        store=store,
        secrets=secrets,
        pool=CredentialPool(store),
    )
    monkeypatch.setattr(routing_api, "get_routing_runtime", lambda: runtime)
    service = SettingsRuntimeActionService(
        memory_store_provider=lambda: None,
        memory_creator=lambda **_values: {},
        provider_registry_provider=lambda: None,
        routing_runtime_provider=lambda: runtime,
        credential_writer=lambda _provider, _secret: None,
        memory_dreaming_runner=lambda: {},
        conversation_memory_importer=lambda _limit: {},
        obsidian_memory_importer=lambda: {},
    )
    actions = AppActionRuntime(settings_runtime_handler=service.execute)
    routing_api.configure_action_dispatcher(
        lambda action_id, arguments: actions.dispatch(
            AppActionRequest(action_id=action_id, arguments=arguments),
            AppActionContext(source="ui"),
        )
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_add_credential_never_echoes_secret(monkeypatch, tmp_path, caplog) -> None:
    client = make_client(monkeypatch, tmp_path)
    secret = "super-secret-routing-sentinel"

    response = client.post(
        "/api/llm-routing/credentials",
        json={"provider": "openrouter", "label": "backup", "secret": secret},
    )

    assert response.status_code == 410
    assert secret not in response.text
    assert secret not in caplog.text
    assert response.json()["detail"]["code"] == "APP_ACTION_REQUIRED"


def test_credential_request_model_excludes_secret_from_repr_and_dump() -> None:
    body = routing_api.CredentialCreateBody(
        provider="openrouter",
        label="backup",
        secret="request-secret-sentinel",
    )

    assert "request-secret-sentinel" not in repr(body)
    assert "secret" not in body.model_dump()


def test_invalid_fallback_chain_is_atomic(monkeypatch, tmp_path) -> None:
    client = make_client(monkeypatch, tmp_path)
    accepted = client.put(
        "/api/llm-routing/fallbacks",
        json={"targets": [{"provider": "openrouter", "model": "one/model"}]},
    )
    assert accepted.status_code == 200

    rejected = client.put(
        "/api/llm-routing/fallbacks",
        json={
            "targets": [
                {"provider": "openrouter", "model": "dup/model"},
                {"provider": "openrouter", "model": "DUP/MODEL"},
            ]
        },
    )

    assert rejected.status_code == 422
    body = client.get("/api/llm-routing/fallbacks").json()
    assert [item["model"] for item in body["targets"]] == ["one/model"]


def test_policy_credentials_strategy_reset_and_status_contract(monkeypatch, tmp_path) -> None:
    client = make_client(monkeypatch, tmp_path)

    policy = client.put(
        "/api/llm-routing/policies/global",
        json={"sort": "price", "ignore": ["Together"], "require_parameters": True},
    )
    credential = client.post(
        "/api/llm-routing/credentials",
        json={"provider": "openrouter", "label": "backup", "secret": "key"},
    )
    strategy = client.put(
        "/api/llm-routing/credentials/openrouter/strategy",
        json={"strategy": "round_robin"},
    )
    reset = client.post("/api/llm-routing/credentials/openrouter/reset")
    status = client.get("/api/llm-routing/status")

    assert policy.status_code == 200
    assert policy.json()["sort"] == "price"
    assert credential.status_code == 410
    assert strategy.json()["strategy"] == "round_robin"
    assert reset.json()["ok"] is True
    assert status.status_code == 200
    assert status.json()["primary_provider"] == "openrouter"
    assert status.json()["global_policy"]["data_collection"] == "deny"
    assert status.json()["credential_health"]["openrouter"]["healthy"] == 0


def test_attempt_endpoint_is_bounded_and_redacted(monkeypatch, tmp_path) -> None:
    client = make_client(monkeypatch, tmp_path)

    response = client.get("/api/llm-routing/attempts?limit=10&offset=0")

    assert response.status_code == 200
    assert response.json() == {"attempts": [], "limit": 10, "offset": 0}
    assert client.get("/api/llm-routing/attempts?limit=501").status_code == 422


def test_main_vellum_app_includes_routing_router(monkeypatch, tmp_path) -> None:
    from agent import api as main_api

    isolated = make_client(monkeypatch, tmp_path)
    del isolated
    client = TestClient(main_api.app)

    response = client.get("/api/llm-routing/status")

    assert response.status_code == 200
