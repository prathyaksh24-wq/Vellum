from __future__ import annotations

import json

from agent.llm.routing.models import CredentialRecord
from agent.llm.routing.runtime import build_routing_runtime
from agent.tools import llm_routing as routing_tool_mod


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class Settings:
    def __init__(self, path):
        self.llm_routing_db_path = path
        self.llm_routing_keyring_service = "vellum.test"
        self.llm_routing_max_targets = 4
        self.llm_routing_max_transient_retries = 2
        self.openrouter_base_url = "https://openrouter.test/v1"
        self.openai_base_url = "https://openai.test/v1"
        self.fallback_model = ""
        self.openrouter_api_key = "or-secret"
        self.openai_api_key = "oa-secret"


def _tool_call(**kwargs):
    return json.loads(routing_tool_mod.llm_routing.invoke(kwargs))


def test_llm_routing_tool_updates_backend_policy_and_fallbacks(monkeypatch, tmp_path) -> None:
    runtime = build_routing_runtime(
        settings=Settings(tmp_path / "routing.db"),
        keyring_backend=FakeKeyring(),
        fingerprint_salt=b"x" * 32,
    )
    monkeypatch.setattr(routing_tool_mod, "get_routing_runtime", lambda: runtime)

    policy = _tool_call(
        action="set_provider_routing",
        sort="price",
        require_parameters=True,
        allow_fallbacks=True,
    )
    fallbacks = _tool_call(
        action="set_fallbacks",
        fallback_models=["deepseek/deepseek-chat", "qwen/qwen3.5-35b-a3b"],
    )

    assert policy["ok"] is True
    assert policy["global_policy"]["sort"] == "price"
    assert policy["global_policy"]["data_collection"] == "deny"
    assert policy["global_policy"]["zdr"] is True
    assert [item["model"] for item in fallbacks["fallbacks"]] == [
        "deepseek/deepseek-v4-pro",
        "qwen/qwen3.5-35b-a3b",
    ]


def test_llm_routing_tool_changes_strategy_without_accepting_secrets(monkeypatch, tmp_path) -> None:
    runtime = build_routing_runtime(
        settings=Settings(tmp_path / "routing.db"),
        keyring_backend=FakeKeyring(),
        fingerprint_salt=b"x" * 32,
    )
    runtime.store.upsert_credential(
        CredentialRecord(
            provider="openrouter",
            label="manual",
            source="keyring:manual",
            fingerprint="fp",
        )
    )
    monkeypatch.setattr(routing_tool_mod, "get_routing_runtime", lambda: runtime)

    body = _tool_call(
        action="set_credential_strategy",
        credential_provider="openrouter",
        credential_strategy="round_robin",
    )

    assert body["ok"] is True
    assert body["credential_health"]["openrouter"]["strategy"] == "round_robin"
