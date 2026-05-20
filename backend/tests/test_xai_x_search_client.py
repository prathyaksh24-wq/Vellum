import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "xai_x_search_client.py"


def _load():
    spec = importlib.util.spec_from_file_location("xai_x_search_client", SCRIPT_PATH)
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


def _xai_payload(text: str) -> dict:
    return {
        "output_text": text,
        "citations": ["https://x.com/naval/status/1234567890123456789"],
    }


def test_fetch_tweets_posts_to_xai_responses_with_oauth_token_and_returns_normalized_items(monkeypatch):
    mod = _load()
    monkeypatch.setenv("XAI_OAUTH_ACCESS_TOKEN", "oauth-access-token")
    response_json = {
        "tweets": [
            {
                "text": "Read. Think. Write.",
                "url": "https://x.com/naval/status/1234567890123456789",
                "created_at": "2026-05-10T10:00:00Z",
            }
        ]
    }
    with patch.object(mod.httpx, "post", return_value=_Response(_xai_payload(json.dumps(response_json)))) as post:
        out = mod.fetch_tweets(
            handle="naval",
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 2, tzinfo=timezone.utc),
            max_items=10,
        )

    url = post.call_args.args[0]
    kwargs = post.call_args.kwargs
    assert url == "https://api.x.ai/v1/responses"
    assert kwargs["headers"]["Authorization"] == "Bearer oauth-access-token"
    assert kwargs["json"]["tools"] == [
        {
            "type": "x_search",
            "allowed_x_handles": ["naval"],
            "from_date": "2026-05-01",
            "to_date": "2026-05-02",
        }
    ]
    assert kwargs["json"]["text"]["format"]["type"] == "json_schema"
    assert kwargs["json"]["text"]["format"]["name"] == "x_tweet_archive"
    assert kwargs["json"]["text"]["format"]["strict"] is True
    assert kwargs["json"]["text"]["format"]["schema"]["required"] == ["tweets"]
    assert out == [
        {
            "id": "1234567890123456789",
            "url": "https://x.com/naval/status/1234567890123456789",
            "text": "Read. Think. Write.",
            "createdAt": "2026-05-10T10:00:00+00:00",
            "isReply": False,
            "isRetweet": False,
            "isQuote": False,
            "media": [],
        }
    ]


def test_fetch_tweets_uses_token_file_and_refreshes_expiring_oauth_token(monkeypatch, tmp_path):
    mod = _load()
    monkeypatch.delenv("XAI_OAUTH_ACCESS_TOKEN", raising=False)
    oauth_file = tmp_path / "xai-oauth.json"
    oauth_file.write_text(
        json.dumps({
            "tokens": {
                "access_token": "expired.jwt.token",
                "refresh_token": "refresh-token",
            },
            "discovery": {"token_endpoint": "https://auth.x.ai/oauth/token"},
            "client_id": "saved-client-id",
        }),
        encoding="utf-8",
    )
    calls = [
        _Response({"access_token": "fresh-token", "refresh_token": "new-refresh"}),
        _Response(_xai_payload('{"tweets": [{"text": "Be useful.", "url": "https://x.com/naval/status/1234567890123456790"}]}')),
    ]

    def fake_post(*_args, **_kwargs):
        return calls.pop(0)

    with patch.object(mod.httpx, "post", side_effect=fake_post) as post:
        out = mod.fetch_tweets(
            handle="naval",
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 2, tzinfo=timezone.utc),
            max_items=10,
            oauth_file=oauth_file,
        )

    assert out[0]["id"] == "1234567890123456790"
    assert post.call_args_list[0].args[0] == "https://auth.x.ai/oauth/token"
    assert post.call_args_list[0].kwargs["data"]["client_id"] == "saved-client-id"
    assert post.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer fresh-token"
    saved = json.loads(oauth_file.read_text(encoding="utf-8"))
    assert saved["tokens"]["access_token"] == "fresh-token"
    assert saved["tokens"]["refresh_token"] == "new-refresh"


def test_fetch_tweets_parses_fenced_json(monkeypatch):
    mod = _load()
    monkeypatch.setenv("XAI_OAUTH_ACCESS_TOKEN", "oauth-access-token")
    stdout = """```json
{"tweets": [{"text": "Be useful.", "url": "https://x.com/naval/status/1234567890123456790"}]}
```"""
    with patch.object(mod.httpx, "post", return_value=_Response(_xai_payload(stdout))):
        out = mod.fetch_tweets(
            handle="naval",
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 2, tzinfo=timezone.utc),
            max_items=10,
        )
    assert out[0]["id"] == "1234567890123456790"
    assert out[0]["text"] == "Be useful."


def test_fetch_tweets_ignores_reasoning_text_when_parsing_response_output(monkeypatch):
    mod = _load()
    monkeypatch.setenv("XAI_OAUTH_ACCESS_TOKEN", "oauth-access-token")
    payload = {
        "output": [
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "This is not JSON."}],
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": '{"tweets": [{"text": "Be useful.", "url": "https://x.com/naval/status/1234567890123456790"}]}',
                    }
                ],
            },
        ]
    }
    with patch.object(mod.httpx, "post", return_value=_Response(payload)):
        out = mod.fetch_tweets(
            handle="naval",
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 2, tzinfo=timezone.utc),
            max_items=10,
        )
    assert out[0]["id"] == "1234567890123456790"


def test_fetch_tweets_extracts_status_id_from_nested_citation_url(monkeypatch):
    mod = _load()
    monkeypatch.setenv("XAI_OAUTH_ACCESS_TOKEN", "oauth-access-token")
    payload = {
        "tweets": [
            {
                "text": "Specific knowledge is earned.",
                "citations": [{"url": "https://twitter.com/naval/status/1234567890123456791"}],
            }
        ]
    }
    with patch.object(mod.httpx, "post", return_value=_Response(_xai_payload(json.dumps(payload)))):
        out = mod.fetch_tweets(
            handle="naval",
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 2, tzinfo=timezone.utc),
            max_items=10,
        )
    assert out[0]["id"] == "1234567890123456791"
    assert out[0]["url"] == "https://x.com/naval/status/1234567890123456791"


def test_fetch_tweets_rejects_uncited_records(monkeypatch):
    mod = _load()
    monkeypatch.setenv("XAI_OAUTH_ACCESS_TOKEN", "oauth-access-token")
    payload = {"tweets": [{"text": "No citation here.", "url": "https://example.com/not-x"}]}
    with patch.object(mod.httpx, "post", return_value=_Response(_xai_payload(json.dumps(payload)))):
        out = mod.fetch_tweets(
            handle="naval",
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 2, tzinfo=timezone.utc),
            max_items=10,
        )
    assert out == []


def test_fetch_tweets_rejects_textless_records(monkeypatch):
    mod = _load()
    monkeypatch.setenv("XAI_OAUTH_ACCESS_TOKEN", "oauth-access-token")
    payload = {"tweets": [{"url": "https://x.com/naval/status/1234567890123456792"}]}
    with patch.object(mod.httpx, "post", return_value=_Response(_xai_payload(json.dumps(payload)))):
        out = mod.fetch_tweets(
            handle="naval",
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 2, tzinfo=timezone.utc),
            max_items=10,
        )
    assert out == []


def test_fetch_tweets_raises_helpful_error_for_malformed_json(monkeypatch):
    mod = _load()
    monkeypatch.setenv("XAI_OAUTH_ACCESS_TOKEN", "oauth-access-token")
    with patch.object(mod.httpx, "post", return_value=_Response(_xai_payload("not json"))):
        with pytest.raises(mod.XAISearchError, match="valid JSON"):
            mod.fetch_tweets(
                handle="naval",
                start=datetime(2026, 5, 1, tzinfo=timezone.utc),
                end=datetime(2026, 5, 2, tzinfo=timezone.utc),
                max_items=10,
            )


def test_fetch_tweets_maps_missing_oauth_to_auth_setup_error(monkeypatch):
    mod = _load()
    monkeypatch.delenv("XAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    with pytest.raises(mod.XAIAuthError, match="XAI_OAUTH_ACCESS_TOKEN"):
        mod.fetch_tweets(
            handle="naval",
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 2, tzinfo=timezone.utc),
            max_items=10,
            oauth_file=Path("does-not-exist.json"),
        )


def test_fetch_tweets_maps_oauth_failures_without_leaking_response_body(monkeypatch):
    mod = _load()
    monkeypatch.setenv("XAI_OAUTH_ACCESS_TOKEN", "oauth-access-token")
    secret_body = "401 invalid_grant refresh_token=secret-token-value"
    with patch.object(mod.httpx, "post", return_value=_Response({"error": "nope"}, status_code=401, text=secret_body)):
        with pytest.raises(mod.XAIAuthError) as exc:
            mod.fetch_tweets(
                handle="naval",
                start=datetime(2026, 5, 1, tzinfo=timezone.utc),
                end=datetime(2026, 5, 2, tzinfo=timezone.utc),
                max_items=10,
            )
    assert "secret-token-value" not in str(exc.value)
    assert "xAI OAuth" in str(exc.value)


def test_search_x_posts_general_query_to_x_search(monkeypatch):
    mod = _load()
    monkeypatch.setenv("XAI_OAUTH_ACCESS_TOKEN", "oauth-access-token")
    response_json = {
        "tweets": [
            {
                "text": "NBA update",
                "url": "https://x.com/NBA/status/1234567890123456799",
                "created_at": "2026-05-20T01:00:00Z",
            }
        ]
    }

    with patch.object(mod.httpx, "post", return_value=_Response(_xai_payload(json.dumps(response_json)))) as post:
        out = mod.search_x(
            query="latest NBA news",
            start=datetime(2026, 5, 19, tzinfo=timezone.utc),
            end=datetime(2026, 5, 20, tzinfo=timezone.utc),
            max_items=5,
        )

    kwargs = post.call_args.kwargs
    assert kwargs["json"]["tools"] == [
        {
            "type": "x_search",
            "from_date": "2026-05-19",
            "to_date": "2026-05-20",
        }
    ]
    assert "latest NBA news" in kwargs["json"]["input"]
    assert out[0]["id"] == "1234567890123456799"
