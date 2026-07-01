"""Spotify PKCE and local credential persistence."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from urllib.parse import urlencode

from .errors import SpotifyAuthError


DEFAULT_SCOPES = (
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-read-recently-played",
    "user-read-private",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-public",
    "playlist-modify-private",
    "user-library-read",
    "user-library-modify",
)


class SpotifyAuthStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.auth_path = self.root / "auth.json"
        self.flow_path = self.root / "oauth-flow.json"

    def save_tokens(self, payload: dict) -> None:
        self._atomic_write(self.auth_path, payload)

    def load_tokens(self) -> dict:
        if not self.auth_path.exists():
            raise SpotifyAuthError("Spotify is not connected")
        return self._read_json(self.auth_path)

    def save_flow(self, payload: dict) -> None:
        self._atomic_write(self.flow_path, payload)

    def consume_flow(self, state: str, *, max_age_seconds: int = 600) -> dict:
        if not self.flow_path.exists():
            raise SpotifyAuthError("Spotify authorization state is missing")
        flow = self._read_json(self.flow_path)
        created_at = float(flow.get("created_at") or 0)
        if time.time() - created_at > max_age_seconds:
            self.flow_path.unlink(missing_ok=True)
            raise SpotifyAuthError("Spotify authorization state expired")
        if not state or not secrets.compare_digest(str(flow.get("state") or ""), state):
            raise SpotifyAuthError("Spotify authorization state did not match")
        self.flow_path.unlink(missing_ok=True)
        return flow

    def logout(self) -> None:
        self.auth_path.unlink(missing_ok=True)
        self.flow_path.unlink(missing_ok=True)

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SpotifyAuthError("Spotify credentials are unreadable") from exc
        if not isinstance(value, dict):
            raise SpotifyAuthError("Spotify credentials are invalid")
        return value

    @staticmethod
    def _atomic_write(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
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
                temp_path = Path(handle.name)
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def new_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    return verifier, pkce_challenge(verifier)


def authorization_url(*, client_id: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    if not all(value.strip() for value in (client_id, redirect_uri, state, code_challenge)):
        raise SpotifyAuthError("Spotify authorization configuration is incomplete")
    query = urlencode(
        {
            "client_id": client_id.strip(),
            "response_type": "code",
            "redirect_uri": redirect_uri.strip(),
            "state": state,
            "scope": " ".join(DEFAULT_SCOPES),
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
        }
    )
    return f"https://accounts.spotify.com/authorize?{query}"
