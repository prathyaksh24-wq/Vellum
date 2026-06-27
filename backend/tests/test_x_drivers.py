import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_script(name: str):
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Client:
    class XAIAuthError(Exception):
        pass

    calls = []

    @staticmethod
    def fetch_tweets(**kwargs):
        _Client.calls.append(kwargs)
        return [{"id": "1", "text": "Read. Think. Write.", "url": "https://x.com/naval/status/1"}]


class _Ingest:
    class Result:
        fetched = 1
        filtered = 0
        added = 1
        total = 1

    @staticmethod
    def ingest(**kwargs):
        return _Ingest.Result()


class _Handle:
    def __init__(self, name: str):
        self.name = name
        self.filter_profile = "aphorism"
        self.dedup_group = name
        self.source_label = "xAI X Search OAuth"


class _HandleConfig:
    HANDLES = [_Handle("naval")]

    @staticmethod
    def get_handle(name: str):
        return _Handle(name)

    @staticmethod
    def vault_base_for(handle, vault_root: Path):
        return vault_root / "Library" / "X" / handle.name


def test_poll_x_does_not_require_apify_token(monkeypatch, tmp_path):
    mod = _load_script("poll_x")
    _Client.calls = []
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    monkeypatch.setenv("XAI_OAUTH_ACCESS_TOKEN", "oauth-token")
    monkeypatch.setattr(mod, "_load", lambda name: {
        "xai_x_search_client": _Client,
        "x_ingest": _Ingest,
        "handle_config": _HandleConfig,
    }[name])

    code = mod.run(tmp_path, dry_run=False, max_items=5, window_hours=8)

    assert code == 0
    assert _Client.calls
    assert _Client.calls[0]["oauth_file"] == tmp_path / "data" / "xai-oauth.json"
    assert "token" not in _Client.calls[0]


def test_poll_x_auth_error_returns_3(monkeypatch, tmp_path):
    mod = _load_script("poll_x")

    class AuthClient(_Client):
        @staticmethod
        def fetch_tweets(**kwargs):
            raise AuthClient.XAIAuthError("set XAI_OAUTH_ACCESS_TOKEN")

    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    monkeypatch.setattr(mod, "_load", lambda name: {
        "xai_x_search_client": AuthClient,
        "x_ingest": _Ingest,
        "handle_config": _HandleConfig,
    }[name])

    assert mod.run(tmp_path, dry_run=False, max_items=5, window_hours=8) == 3


def test_backfill_x_uses_seven_day_windows_and_no_apify_token(monkeypatch, tmp_path):
    mod = _load_script("backfill_x")
    _Client.calls = []
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    monkeypatch.setenv("XAI_OAUTH_ACCESS_TOKEN", "oauth-token")
    monkeypatch.setattr(mod, "_load", lambda name: {
        "xai_x_search_client": _Client,
        "x_ingest": _Ingest,
        "handle_config": _HandleConfig,
    }[name])
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        mod,
        "datetime",
        type("FrozenDatetime", (), {
            "now": staticmethod(lambda tz=None: datetime(2026, 5, 15, tzinfo=timezone.utc)),
        }),
    )

    code = mod.run(tmp_path, only_handle="naval", days=14, max_per_window=5)

    assert code == 0
    assert len(_Client.calls) == 2
    assert all((call["end"] - call["start"]).days == 7 for call in _Client.calls)
    assert all(call["oauth_file"] == tmp_path / "data" / "xai-oauth.json" for call in _Client.calls)
    assert all("token" not in call for call in _Client.calls)
