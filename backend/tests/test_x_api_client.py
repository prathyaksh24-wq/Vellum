import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "x_api_client.py"


def _load():
    spec = importlib.util.spec_from_file_location("x_api_client", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


def _oauth_file(tmp_path: Path, access_token: str = "access-token") -> Path:
    path = tmp_path / "x-api-oauth.json"
    path.write_text(
        json.dumps({
            "provider": "x-api-oauth",
            "client_id": "client-123",
            "token_endpoint": "https://api.x.com/2/oauth2/token",
            "tokens": {"access_token": access_token, "refresh_token": "refresh-token"},
        }),
        encoding="utf-8",
    )
    return path


def test_get_me_calls_authenticated_user_endpoint(tmp_path):
    mod = _load()
    oauth_file = _oauth_file(tmp_path)

    with patch.object(mod.httpx, "get", return_value=_Response({"data": {"id": "42", "username": "me"}})) as get:
        out = mod.get_me(oauth_file=oauth_file)

    assert out["data"]["username"] == "me"
    assert get.call_args.args[0] == "https://api.x.com/2/users/me"
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer access-token"


def test_get_bookmarks_uses_user_id_and_tweet_fields(tmp_path):
    mod = _load()
    oauth_file = _oauth_file(tmp_path)

    with patch.object(mod.httpx, "get", return_value=_Response({"data": [{"id": "1", "text": "Saved"}]})) as get:
        out = mod.get_bookmarks(user_id="42", max_results=25, oauth_file=oauth_file)

    assert out["data"][0]["text"] == "Saved"
    assert get.call_args.args[0] == "https://api.x.com/2/users/42/bookmarks"
    assert get.call_args.kwargs["params"]["max_results"] == 25
    assert "created_at" in get.call_args.kwargs["params"]["tweet.fields"]


def test_post_tweet_posts_json_body(tmp_path):
    mod = _load()
    oauth_file = _oauth_file(tmp_path)

    with patch.object(mod.httpx, "post", return_value=_Response({"data": {"id": "99", "text": "Hello"}})) as post:
        out = mod.post_tweet(text="Hello", oauth_file=oauth_file)

    assert out["data"]["id"] == "99"
    assert post.call_args.args[0] == "https://api.x.com/2/tweets"
    assert post.call_args.kwargs["json"] == {"text": "Hello"}
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer access-token"


def test_refresh_uses_saved_client_id_without_leaking_token(tmp_path):
    mod = _load()
    oauth_file = _oauth_file(tmp_path, access_token="expired.jwt.token")
    calls = [
        _Response({"access_token": "fresh-token", "refresh_token": "new-refresh"}),
        _Response({"data": {"id": "42", "username": "me"}}),
    ]

    def fake_post(*_args, **_kwargs):
        return calls.pop(0)

    with patch.object(mod.httpx, "post", side_effect=fake_post) as post, patch.object(mod.httpx, "get", return_value=calls[-1]):
        mod.get_me(oauth_file=oauth_file)

    assert post.call_args.args[0] == "https://api.x.com/2/oauth2/token"
    assert post.call_args.kwargs["data"]["client_id"] == "client-123"
    saved = json.loads(oauth_file.read_text(encoding="utf-8"))
    assert saved["tokens"]["access_token"] == "fresh-token"


def test_missing_oauth_file_raises_setup_error(tmp_path):
    mod = _load()

    with pytest.raises(mod.XApiAuthError, match="setup_x_api_oauth"):
        mod.get_me(oauth_file=tmp_path / "missing.json")


def test_auth_error_is_sanitized(tmp_path):
    mod = _load()
    oauth_file = _oauth_file(tmp_path)

    with patch.object(mod.httpx, "get", return_value=_Response({"error": "nope"}, status_code=403, text="secret refresh-token")):
        with pytest.raises(mod.XApiAuthError) as exc:
            mod.get_me(oauth_file=oauth_file)

    assert "secret" not in str(exc.value)
    assert "X API OAuth" in str(exc.value)
