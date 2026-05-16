import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "naval_x_ingest.py"


def _load():
    spec = importlib.util.spec_from_file_location("naval_x_ingest", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _apify_item(status_id: str, text: str, **kwargs) -> dict:
    base = {
        "id": status_id,
        "url": f"https://x.com/naval/status/{status_id}",
        "text": text,
        "createdAt": "2026-05-12T10:00:00.000Z",
        "isReply": False,
        "isRetweet": False,
        "isQuote": False,
        "media": [],
    }
    base.update(kwargs)
    return base


def test_tweet_from_apify_item_maps_core_fields():
    mod = _load()
    tweet = mod.tweet_from_apify_item(_apify_item("123", "Hello."))
    assert tweet is not None
    assert tweet.status_id == "123"
    assert tweet.text == "Hello."
    assert tweet.x_url == "https://x.com/naval/status/123"
    assert tweet.posted_utc.startswith("2026-05-12T10:00:00")
    assert tweet.source == "Apify apidojo/tweet-scraper"


def test_tweet_from_apify_item_returns_none_without_id():
    mod = _load()
    item = _apify_item("123", "Hello.")
    item.pop("id")
    item["url"] = "https://x.com/naval"  # no /status/
    assert mod.tweet_from_apify_item(item) is None


def test_ingest_filters_non_aphorisms_and_dedupes(tmp_path):
    mod = _load()
    base = tmp_path / "X" / "naval"
    base.mkdir(parents=True)

    items = [
        _apify_item("1001", "Be honest with yourself."),
        _apify_item("1002", "Read https://example.com/article now"),  # URL -> reject
        _apify_item("1003", "@bob nope"),  # mention -> reject
        _apify_item("1004", "Calm beats anxious."),
        _apify_item("1001", "Duplicate."),  # dupe status_id -> ignored
    ]
    result = mod.ingest(base=base, items=items)
    assert result.added == 2
    assert result.filtered == 3
    manifest = json.loads((base / "naval-tweets.json").read_text(encoding="utf-8"))
    status_ids = {row["status_id"] for row in manifest}
    assert status_ids == {"1001", "1004"}
    assert (base / "latest-50.md").exists()
    assert (base / "naval-tweets.jsonl").exists()
    assert (base / ".state" / "naval_x_scraper_state.json").exists()


def test_ingest_merges_with_existing_manifest(tmp_path):
    mod = _load()
    base = tmp_path / "X" / "naval"
    base.mkdir(parents=True)
    # Seed an existing manifest
    seed = [{
        "status_id": "9000",
        "posted_utc": "2026-01-01T00:00:00+00:00",
        "text": "Seeded wisdom.",
        "text_hash": "abc",
        "topics": ["general"],
        "x_url": "https://x.com/naval/status/9000",
        "mirror_url": "x",
        "source": "Existing",
        "note_path": "Vault/X/naval/tweets/2026/2026-01-01-9000-seeded-wisdom.md",
    }]
    (base / "naval-tweets.json").write_text(json.dumps(seed), encoding="utf-8")

    items = [_apify_item("1001", "Fresh wisdom is timeless.")]
    result = mod.ingest(base=base, items=items)
    assert result.added == 1
    manifest = json.loads((base / "naval-tweets.json").read_text(encoding="utf-8"))
    ids = {row["status_id"] for row in manifest}
    assert ids == {"9000", "1001"}
