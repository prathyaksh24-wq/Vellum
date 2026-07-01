from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from typing import Protocol
from uuid import uuid4

from agent.llm.routing.models import CredentialRecord, CredentialStatus
from agent.llm.routing.store import RoutingStore


class KeyringBackend(Protocol):
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def get_password(self, service: str, username: str) -> str | None: ...
    def delete_password(self, service: str, username: str) -> None: ...


class SecretUnavailable(RuntimeError):
    """Raised without secret-bearing provider or backend details."""


class SecretResolver:
    def __init__(
        self,
        store: RoutingStore,
        keyring_backend: KeyringBackend | None = None,
        *,
        service: str = "vellum.llm",
        fingerprint_salt: bytes | None = None,
    ) -> None:
        if keyring_backend is None:
            import keyring

            keyring_backend = keyring
        self.store = store
        self.keyring = keyring_backend
        self.service = service
        self._fingerprint_salt = fingerprint_salt
        self._runtime_values: dict[str, str] = {}

    def _salt(self) -> bytes:
        if self._fingerprint_salt is not None:
            return self._fingerprint_salt
        username = "__fingerprint_salt__"
        try:
            encoded = self.keyring.get_password(self.service, username)
            if encoded:
                self._fingerprint_salt = base64.urlsafe_b64decode(encoded.encode("ascii"))
                return self._fingerprint_salt
            salt = secrets.token_bytes(32)
            self.keyring.set_password(
                self.service,
                username,
                base64.urlsafe_b64encode(salt).decode("ascii"),
            )
            self._fingerprint_salt = salt
            return salt
        except Exception as exc:
            raise SecretUnavailable("OS credential storage is unavailable") from exc

    def fingerprint(self, secret: str) -> str:
        digest = hmac.new(self._salt(), secret.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"

    def reconcile_environment(self, provider_variables: dict[str, str]) -> None:
        for provider, variable in provider_variables.items():
            source = f"env:{variable}"
            value = os.environ.get(variable)
            existing = next(
                (
                    item
                    for item in self.store.list_credentials(provider)
                    if item.source == source
                ),
                None,
            )
            if value:
                if existing is None:
                    record = CredentialRecord(
                        provider=provider,
                        label=variable,
                        source=source,
                        fingerprint=self.fingerprint(value),
                    )
                else:
                    record = existing.model_copy(
                        update={
                            "label": variable,
                            "fingerprint": self.fingerprint(value),
                        }
                    )
                self.store.upsert_credential(record)
            elif existing is not None:
                self.store.set_credential_state(
                    existing.id,
                    status=CredentialStatus.unavailable,
                    cooldown_until=None,
                    consecutive_429=existing.consecutive_429,
                )

    def add_manual(self, provider: str, label: str, secret: str) -> CredentialRecord:
        normalized_secret = secret.strip()
        if not normalized_secret:
            raise ValueError("secret cannot be empty")
        credential_id = uuid4().hex
        record = CredentialRecord(
            id=credential_id,
            provider=provider,
            label=label,
            source=f"keyring:{credential_id}",
            fingerprint=self.fingerprint(normalized_secret),
        )
        try:
            self.keyring.set_password(self.service, credential_id, normalized_secret)
            return self.store.upsert_credential(record)
        except Exception as exc:
            try:
                self.keyring.delete_password(self.service, credential_id)
            except Exception:
                pass
            if isinstance(exc, ValueError):
                raise
            raise SecretUnavailable("credential could not be stored") from exc

    def reconcile_borrowed(
        self,
        provider: str,
        label: str,
        secret: str,
    ) -> CredentialRecord:
        source = f"runtime:{label}"
        existing = next(
            (item for item in self.store.list_credentials(provider) if item.source == source),
            None,
        )
        if existing is None:
            record = CredentialRecord(
                provider=provider,
                label=label,
                source=source,
                fingerprint=self.fingerprint(secret),
            )
        else:
            record = existing.model_copy(
                update={"label": label, "fingerprint": self.fingerprint(secret)}
            )
        self._runtime_values[source] = secret
        return self.store.upsert_credential(record)

    def resolve(self, credential: CredentialRecord) -> str:
        if credential.source.startswith("env:"):
            value = os.environ.get(credential.source.removeprefix("env:"))
        elif credential.source.startswith("keyring:"):
            try:
                value = self.keyring.get_password(
                    self.service,
                    credential.source.removeprefix("keyring:"),
                )
            except Exception as exc:
                raise SecretUnavailable("OS credential storage is unavailable") from exc
        elif credential.source.startswith("runtime:"):
            value = self._runtime_values.get(credential.source)
        else:
            value = None
        if not value:
            raise SecretUnavailable(f"credential {credential.id} is unavailable")
        return value

    def remove_manual(self, credential_id: str) -> None:
        credential = self.store.get_credential(credential_id)
        if credential is None:
            raise KeyError(credential_id)
        if not credential.source.startswith("keyring:"):
            raise ValueError("borrowed credentials must be removed at their source")
        if self.store.has_active_leases(credential_id):
            raise RuntimeError("credential has active leases")
        try:
            self.keyring.delete_password(self.service, credential_id)
        except Exception as exc:
            raise SecretUnavailable("credential could not be removed") from exc
        self.store.delete_credential(credential_id)

    @staticmethod
    def public_record(credential: CredentialRecord) -> CredentialRecord:
        return credential.model_copy(deep=True)
