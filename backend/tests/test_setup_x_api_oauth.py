import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "setup_x_api_oauth.py"


def _load():
    spec = importlib.util.spec_from_file_location("setup_x_api_oauth", SCRIPT_PATH)
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


def test_authorize_url_uses_x_api_scopes_and_loopback_redirect():
    mod = _load()

    url = mod.build_authorize_url(
        client_id="client-123",
        redirect_uri="http://127.0.0.1:56122/callback",
        state="state-123",
        code_challenge="challenge-123",
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "x.com"
    assert parsed.path == "/i/oauth2/authorize"
    assert query["client_id"] == ["client-123"]
    assert query["redirect_uri"] == ["http://127.0.0.1:56122/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == [mod.X_API_OAUTH_SCOPE]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == ["challenge-123"]
    assert query["state"] == ["state-123"]


def test_exchange_code_posts_pkce_payload_without_client_secret():
    mod = _load()

    with patch.object(mod.httpx, "post", return_value=_Response({"access_token": "access", "refresh_token": "refresh"})) as post:
        tokens = mod.exchange_authorization_code(
            client_id="client-123",
            client_secret="",
            code="auth-code",
            redirect_uri="http://127.0.0.1:56122/callback",
            code_verifier="verifier-123",
            timeout_secs=30,
        )

    assert tokens["access_token"] == "access"
    data = post.call_args.kwargs["data"]
    assert data["grant_type"] == "authorization_code"
    assert data["client_id"] == "client-123"
    assert data["code"] == "auth-code"
    assert data["redirect_uri"] == "http://127.0.0.1:56122/callback"
    assert data["code_verifier"] == "verifier-123"
    assert "client_secret" not in data


def test_save_oauth_file_writes_refreshable_token_store(tmp_path):
    mod = _load()
    oauth_file = tmp_path / "data" / "x-api-oauth.json"

    mod.save_oauth_file(
        oauth_file,
        client_id="client-123",
        tokens={"access_token": "access", "refresh_token": "refresh", "expires_in": 7200},
    )

    saved = json.loads(oauth_file.read_text(encoding="utf-8"))
    assert saved["provider"] == "x-api-oauth"
    assert saved["client_id"] == "client-123"
    assert saved["scope"] == mod.X_API_OAUTH_SCOPE
    assert saved["base_url"] == "https://api.x.com/2"
    assert saved["tokens"]["access_token"] == "access"
    assert saved["tokens"]["refresh_token"] == "refresh"
    assert saved["token_endpoint"] == "https://api.x.com/2/oauth2/token"
