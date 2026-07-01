from __future__ import annotations

from types import SimpleNamespace

from agent.llm.routing.models import FallbackTarget
from agent.llm.routing.runtime import build_routing_runtime


class FakeKeyring:
    def __init__(self) -> None:
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


def settings_for(tmp_path):
    return SimpleNamespace(
        llm_routing_db_path=tmp_path / "routing.db",
        llm_routing_keyring_service="vellum.test",
        llm_routing_max_targets=4,
        llm_routing_max_transient_retries=2,
        openrouter_base_url="https://openrouter.test/v1",
        openai_base_url="https://openai.test/v1",
        fallback_model="qwen/fallback",
    )


def test_runtime_seeds_environment_credentials_and_legacy_fallback(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")

    runtime = build_routing_runtime(
        settings=settings_for(tmp_path),
        keyring_backend=FakeKeyring(),
        fingerprint_salt=b"test-salt",
    )

    assert len(runtime.store.list_credentials("openrouter")) == 1
    assert len(runtime.store.list_credentials("openai")) == 1
    assert runtime.store.list_fallbacks()[0].model == "qwen/fallback"


def test_runtime_does_not_overwrite_explicit_fallback_chain(tmp_path) -> None:
    settings = settings_for(tmp_path)
    runtime = build_routing_runtime(
        settings=settings,
        keyring_backend=FakeKeyring(),
        fingerprint_salt=b"test-salt",
    )
    runtime.store.replace_fallbacks(
        [FallbackTarget(provider="openrouter", model="custom/fallback")]
    )

    rebuilt = build_routing_runtime(
        settings=settings,
        keyring_backend=FakeKeyring(),
        fingerprint_salt=b"test-salt",
    )

    assert rebuilt.store.list_fallbacks()[0].model == "custom/fallback"


def test_runtime_does_not_reseed_fallback_after_explicit_clear(tmp_path) -> None:
    settings = settings_for(tmp_path)
    runtime = build_routing_runtime(
        settings=settings,
        keyring_backend=FakeKeyring(),
        fingerprint_salt=b"test-salt",
    )
    runtime.store.replace_fallbacks([])

    rebuilt = build_routing_runtime(
        settings=settings,
        keyring_backend=FakeKeyring(),
        fingerprint_salt=b"test-salt",
    )

    assert rebuilt.store.list_fallbacks() == []
