import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest

from plugins.connectors.spotify.auth import (
    DEFAULT_SCOPES,
    SpotifyAuthStore,
    authorization_url,
    new_pkce_pair,
    pkce_challenge,
)
from plugins.connectors.spotify.errors import SpotifyAuthError


def test_pkce_challenge_uses_s256():
    verifier = "a" * 64
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")

    assert pkce_challenge(verifier) == expected


def test_new_pkce_pair_returns_matching_verifier_and_challenge():
    verifier, challenge = new_pkce_pair()

    assert 43 <= len(verifier) <= 128
    assert challenge == pkce_challenge(verifier)


def test_authorization_url_contains_pkce_and_scopes():
    url = authorization_url(
        client_id="client-123",
        redirect_uri="http://127.0.0.1:8000/api/plugins/spotify/oauth/callback",
        state="state-123",
        code_challenge="challenge-123",
    )

    query = parse_qs(urlparse(url).query)
    assert query["client_id"] == ["client-123"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == ["state-123"]
    assert query["scope"] == [" ".join(DEFAULT_SCOPES)]


def test_complete_flow_rejects_wrong_state(tmp_path):
    store = SpotifyAuthStore(tmp_path)
    store.save_flow({"state": "expected", "code_verifier": "v", "created_at": time.time()})

    with pytest.raises(SpotifyAuthError, match="state"):
        store.consume_flow("wrong")


def test_complete_flow_rejects_expired_state(tmp_path):
    store = SpotifyAuthStore(tmp_path)
    store.save_flow({"state": "expected", "code_verifier": "v", "created_at": time.time() - 601})

    with pytest.raises(SpotifyAuthError, match="expired"):
        store.consume_flow("expected")

    assert not store.flow_path.exists()


def test_token_write_is_atomic_and_round_trips(tmp_path):
    store = SpotifyAuthStore(tmp_path)
    payload = {"client_id": "client", "access_token": "access", "refresh_token": "refresh", "expires_at": 42}

    store.save_tokens(payload)

    assert store.load_tokens() == payload
    assert json.loads(store.auth_path.read_text(encoding="utf-8")) == payload
    assert list(tmp_path.glob("*.tmp")) == []


def test_logout_removes_tokens_and_flow(tmp_path):
    store = SpotifyAuthStore(tmp_path)
    store.save_tokens({"access_token": "a", "refresh_token": "r", "expires_at": 1})
    store.save_flow({"state": "s", "code_verifier": "v", "created_at": time.time()})

    store.logout()

    assert not store.auth_path.exists()
    assert not store.flow_path.exists()
