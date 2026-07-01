from __future__ import annotations

from datetime import UTC, datetime

from agent.llm.routing.models import CredentialStatus
from agent.llm.routing.secrets import SecretResolver, SecretUnavailable
from agent.llm.routing.store import RoutingStore


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


def test_environment_secret_is_resolved_but_never_persisted(monkeypatch, tmp_path) -> None:
    secret = "routing-secret-sentinel-environment"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    store = RoutingStore(tmp_path / "routing.db")
    resolver = SecretResolver(
        store=store,
        keyring_backend=FakeKeyring(),
        fingerprint_salt=b"test-salt",
    )

    resolver.reconcile_environment({"openrouter": "OPENROUTER_API_KEY"})
    record = store.list_credentials("openrouter")[0]

    assert record.source == "env:OPENROUTER_API_KEY"
    assert resolver.resolve(record) == secret
    for database_file in tmp_path.glob("routing.db*"):
        assert secret.encode() not in database_file.read_bytes()


def test_manual_secret_round_trips_only_through_keyring(tmp_path) -> None:
    keyring = FakeKeyring()
    store = RoutingStore(tmp_path / "routing.db")
    resolver = SecretResolver(
        store=store,
        keyring_backend=keyring,
        fingerprint_salt=b"test-salt",
    )

    record = resolver.add_manual("openrouter", "backup", "manual-secret-sentinel")

    assert keyring.get_password("vellum.llm", record.id) == "manual-secret-sentinel"
    assert resolver.resolve(record) == "manual-secret-sentinel"
    assert "manual-secret-sentinel" not in record.model_dump_json()
    for database_file in tmp_path.glob("routing.db*"):
        assert b"manual-secret-sentinel" not in database_file.read_bytes()


def test_missing_environment_secret_is_marked_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "temporary")
    store = RoutingStore(tmp_path / "routing.db")
    resolver = SecretResolver(store, FakeKeyring(), fingerprint_salt=b"test-salt")
    resolver.reconcile_environment({"openai": "OPENAI_API_KEY"})
    record = store.list_credentials("openai")[0]
    monkeypatch.delenv("OPENAI_API_KEY")

    resolver.reconcile_environment({"openai": "OPENAI_API_KEY"})

    updated = store.get_credential(record.id)
    assert updated is not None
    assert updated.status.value == "unavailable"
    try:
        resolver.resolve(updated)
    except SecretUnavailable as exc:
        assert "temporary" not in str(exc)
    else:
        raise AssertionError("missing environment reference should not resolve")


def test_fingerprints_are_stable_but_do_not_contain_secret(tmp_path) -> None:
    resolver = SecretResolver(
        RoutingStore(tmp_path / "routing.db"),
        FakeKeyring(),
        fingerprint_salt=b"fixed-salt",
    )

    first = resolver.fingerprint("same-secret")
    second = resolver.fingerprint("same-secret")

    assert first == second
    assert first.startswith("hmac-sha256:")
    assert "same-secret" not in first


def test_environment_reconciliation_preserves_existing_cooldown(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "same-key")
    store = RoutingStore(tmp_path / "routing.db")
    resolver = SecretResolver(store, FakeKeyring(), fingerprint_salt=b"test-salt")
    resolver.reconcile_environment({"openrouter": "OPENROUTER_API_KEY"})
    record = store.list_credentials("openrouter")[0]
    cooldown = datetime(2030, 1, 1, tzinfo=UTC)
    store.set_credential_state(
        record.id,
        status=CredentialStatus.cooldown,
        cooldown_until=cooldown,
        consecutive_429=2,
    )

    resolver.reconcile_environment({"openrouter": "OPENROUTER_API_KEY"})

    updated = store.get_credential(record.id)
    assert updated.status is CredentialStatus.cooldown
    assert updated.cooldown_until == cooldown
    assert updated.consecutive_429 == 2


def test_borrowed_settings_secret_is_reference_only_and_resolves_in_memory(tmp_path) -> None:
    secret = "settings-secret-sentinel"
    store = RoutingStore(tmp_path / "routing.db")
    resolver = SecretResolver(store, FakeKeyring(), fingerprint_salt=b"test-salt")

    record = resolver.reconcile_borrowed("openrouter", "OPENROUTER_API_KEY", secret)

    assert record.source == "runtime:OPENROUTER_API_KEY"
    assert resolver.resolve(record) == secret
    for database_file in tmp_path.glob("routing.db*"):
        assert secret.encode() not in database_file.read_bytes()
