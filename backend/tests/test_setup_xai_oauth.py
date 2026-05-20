import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "setup_xai_oauth.py"


def _load():
    spec = importlib.util.spec_from_file_location("setup_xai_oauth", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


def test_authorize_url_uses_xai_pkce_and_loopback_redirect():
    mod = _load()

    url = mod.build_authorize_url(
        authorization_endpoint="https://auth.x.ai/oauth2/auth",
        redirect_uri="http://127.0.0.1:56121/callback",
        state="state-123",
        nonce="nonce-123",
        code_challenge="challenge-123",
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "auth.x.ai"
    assert query["client_id"] == [mod.XAI_OAUTH_CLIENT_ID]
    assert query["redirect_uri"] == ["http://127.0.0.1:56121/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == [mod.XAI_OAUTH_SCOPE]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == ["challenge-123"]
    assert query["state"] == ["state-123"]
    assert query["nonce"] == ["nonce-123"]


def test_exchange_code_posts_pkce_payload_without_client_secret():
    mod = _load()

    with patch.object(mod.httpx, "post", return_value=_Response({"access_token": "access", "refresh_token": "refresh"})) as post:
        tokens = mod.exchange_authorization_code(
            token_endpoint="https://auth.x.ai/oauth/token",
            code="auth-code",
            redirect_uri="http://127.0.0.1:56121/callback",
            code_verifier="verifier-123",
            code_challenge="challenge-123",
            timeout_secs=30,
        )

    assert tokens["access_token"] == "access"
    data = post.call_args.kwargs["data"]
    assert data["grant_type"] == "authorization_code"
    assert data["client_id"] == mod.XAI_OAUTH_CLIENT_ID
    assert data["code"] == "auth-code"
    assert data["redirect_uri"] == "http://127.0.0.1:56121/callback"
    assert data["code_verifier"] == "verifier-123"
    assert data["code_challenge"] == "challenge-123"
    assert data["code_challenge_method"] == "S256"
    assert "client_secret" not in data


def test_save_oauth_file_writes_refreshable_token_store(tmp_path):
    mod = _load()
    oauth_file = tmp_path / "data" / "xai-oauth.json"
    discovery = {
        "authorization_endpoint": "https://auth.x.ai/oauth2/auth",
        "token_endpoint": "https://auth.x.ai/oauth/token",
    }

    mod.save_oauth_file(
        oauth_file,
        tokens={"access_token": "access", "refresh_token": "refresh", "expires_in": 3600},
        discovery=discovery,
    )

    saved = json.loads(oauth_file.read_text(encoding="utf-8"))
    assert saved["provider"] == "xai-oauth"
    assert saved["client_id"] == mod.XAI_OAUTH_CLIENT_ID
    assert saved["scope"] == mod.XAI_OAUTH_SCOPE
    assert saved["base_url"] == "https://api.x.ai/v1"
    assert saved["tokens"]["access_token"] == "access"
    assert saved["tokens"]["refresh_token"] == "refresh"
    assert saved["discovery"]["token_endpoint"] == "https://auth.x.ai/oauth/token"
