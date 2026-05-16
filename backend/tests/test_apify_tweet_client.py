import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "apify_tweet_client.py"


def _load():
    spec = importlib.util.spec_from_file_location("apify_tweet_client", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fetch_tweets_builds_expected_input_and_returns_items():
    mod = _load()
    fake_items = [{"id": "1", "text": "hello"}, {"id": "2", "text": "world"}]

    with patch.object(mod, "ApifyClient") as ClientCls:
        client = ClientCls.return_value
        actor = client.actor.return_value
        actor.call.return_value = {"defaultDatasetId": "ds-123"}
        dataset = client.dataset.return_value
        dataset.iterate_items.return_value = iter(fake_items)

        out = mod.fetch_tweets(
            handle="naval",
            start=datetime(2026, 4, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 1, tzinfo=timezone.utc),
            max_items=100,
            token="apify-test-token",
        )

    ClientCls.assert_called_once_with("apify-test-token")
    client.actor.assert_called_once_with(mod.ACTOR_ID)
    run_input = actor.call.call_args.kwargs["run_input"]
    assert run_input["twitterHandles"] == ["naval"]
    assert run_input["start"] == "2026-04-01"
    assert run_input["end"] == "2026-05-01"
    assert run_input["maxItems"] == 100
    assert run_input["sort"] == "Latest"
    assert actor.call.call_args.kwargs.get("max_items") == 100
    client.dataset.assert_called_once_with("ds-123")
    assert out == fake_items


def test_fetch_tweets_raises_when_run_is_none():
    mod = _load()
    with patch.object(mod, "ApifyClient") as ClientCls:
        client = ClientCls.return_value
        client.actor.return_value.call.return_value = None
        import pytest as _pytest
        with _pytest.raises(RuntimeError):
            mod.fetch_tweets(
                handle="naval",
                start=datetime(2026, 4, 1, tzinfo=timezone.utc),
                end=datetime(2026, 5, 1, tzinfo=timezone.utc),
                max_items=10,
                token="t",
            )
