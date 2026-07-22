"""Google OAuth helpers and local credential persistence for YouTube."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from typing import Any, Protocol
from urllib.parse import urlencode

from .errors import YouTubeAuthError


AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DEFAULT_SCOPES = ("https://www.googleapis.com/auth/youtube.readonly",)


class KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


class YouTubeAuthStore:
    def __init__(
        self,
        root: str | Path,
        *,
        keyring_backend: KeyringBackend | None = None,
        keyring_service: str = "vellum.youtube",
        account_label: str = "primary",
    ) -> None:
        if keyring_backend is None:
            import keyring

            keyring_backend = keyring
        self.root = Path(root)
        self.metadata_path = self.root / "account.json"
        self.flow_path = self.root / "oauth-flow.json"
        self.keyring = keyring_backend
        self.keyring_service = keyring_service.strip() or "vellum.youtube"
        self.account_label = account_label.strip() or "primary"

    def save_tokens(self, payload: dict[str, Any]) -> dict[str, Any]:
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise YouTubeAuthError("YouTube token response is incomplete")
        existing = self.load_tokens(required=False)
        refresh_token = str(payload.get("refresh_token") or existing.get("refresh_token") or "").strip()
        expires_at = float(payload.get("expires_at") or 0)
        if not expires_at:
            expires_at = time.time() + max(0, int(payload.get("expires_in") or 0))
        tokens = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "token_type": str(payload.get("token_type") or existing.get("token_type") or "Bearer"),
            "scope": str(payload.get("scope") or existing.get("scope") or " ".join(DEFAULT_SCOPES)),
        }
        try:
            self.keyring.set_password(
                self.keyring_service,
                self.account_label,
                json.dumps(tokens, ensure_ascii=False, separators=(",", ":")),
            )
        except Exception as exc:
            raise YouTubeAuthError("YouTube tokens could not be stored in the system keyring") from exc
        metadata = self.load_metadata()
        metadata.update(
            {
                "account_label": self.account_label,
                "scope": tokens["scope"],
                "expires_at": expires_at,
                "updated_at": time.time(),
            }
        )
        self._atomic_write(self.metadata_path, metadata)
        return tokens

    def load_tokens(self, *, required: bool = True) -> dict[str, Any]:
        try:
            encoded = self.keyring.get_password(self.keyring_service, self.account_label)
        except Exception as exc:
            raise YouTubeAuthError("YouTube tokens could not be read from the system keyring") from exc
        if not encoded:
            if required:
                raise YouTubeAuthError("YouTube is not connected")
            return {}
        try:
            tokens = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise YouTubeAuthError("YouTube credentials are invalid") from exc
        if not isinstance(tokens, dict) or not str(tokens.get("access_token") or ""):
            raise YouTubeAuthError("YouTube credentials are invalid")
        return tokens

    def save_profile(self, profile: dict[str, Any]) -> None:
        metadata = self.load_metadata()
        metadata.update(
            {
                "channel_id": str(profile.get("channel_id") or ""),
                "channel_title": str(profile.get("title") or ""),
                "updated_at": time.time(),
            }
        )
        self._atomic_write(self.metadata_path, metadata)

    def load_metadata(self) -> dict[str, Any]:
        if not self.metadata_path.exists():
            return {}
        return self._read_json(self.metadata_path, "YouTube account metadata is unreadable")

    def save_flow(self, payload: dict[str, Any]) -> None:
        self._atomic_write(self.flow_path, payload)

    def consume_flow(self, state: str, *, max_age_seconds: int = 600) -> dict[str, Any]:
        if not self.flow_path.exists():
            raise YouTubeAuthError("YouTube authorization state is missing")
        flow = self._read_json(self.flow_path, "YouTube authorization state is unreadable")
        created_at = float(flow.get("created_at") or 0)
        if not created_at or time.time() - created_at > max_age_seconds:
            self.flow_path.unlink(missing_ok=True)
            raise YouTubeAuthError("YouTube authorization state expired")
        if not state or not secrets.compare_digest(str(flow.get("state") or ""), state):
            raise YouTubeAuthError("YouTube authorization state did not match")
        self.flow_path.unlink(missing_ok=True)
        return flow

    def clear(self) -> None:
        try:
            if self.keyring.get_password(self.keyring_service, self.account_label):
                self.keyring.delete_password(self.keyring_service, self.account_label)
        except Exception as exc:
            raise YouTubeAuthError("YouTube tokens could not be removed from the system keyring") from exc
        self.metadata_path.unlink(missing_ok=True)
        self.flow_path.unlink(missing_ok=True)

    @staticmethod
    def _read_json(path: Path, message: str) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise YouTubeAuthError(message) from exc
        if not isinstance(value, dict):
            raise YouTubeAuthError(message)
        return value

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".tmp",
                prefix=path.stem + "-",
                dir=path.parent,
                delete=False,
            ) as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def new_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    return verifier, pkce_challenge(verifier)


def authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    if not all(value.strip() for value in (client_id, redirect_uri, state, code_challenge)):
        raise YouTubeAuthError("YouTube authorization configuration is incomplete")
    query = urlencode(
        {
            "client_id": client_id.strip(),
            "redirect_uri": redirect_uri.strip(),
            "response_type": "code",
            "scope": " ".join(DEFAULT_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZATION_URL}?{query}"
