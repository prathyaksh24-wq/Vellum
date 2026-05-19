import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "x_ingest.py"


def _load(name: str = "x_ingest"):
    sp = SCRIPT_PATH if name == "x_ingest" else Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, sp)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _apify_item(status_id: str, text: str, **overrides) -> dict:
    base = {
        "id": status_id,
        "url": f"https://x.com/test/status/{status_id}",
        "text": text,
        "createdAt": "2026-05-10T10:00:00.000Z",
        "isReply": False,
        "isRetweet": False,
        "isQuote": False,
        "media": [],
    }
    base.update(overrides)
    return base


def test_ingest_writes_filtered_aphorisms_for_naval(tmp_path):
    mod = _load()
    hc_mod = _load("handle_config")
    naval = next(h for h in hc_mod.HANDLES if h.name == "naval")

    items = [
        _apify_item("1001", "Read. Think. Write."),         # aphorism
        _apify_item("1002", "@bob nope"),                    # rejected (mention)
        _apify_item("1003", "Be honest with yourself."),    # aphorism
    ]
    result = mod.ingest(handle=naval, vault_root=tmp_path, items=items)
    assert result.added == 2
    assert result.filtered == 1

    base = tmp_path / "Library" / "X" / "naval"
    manifest = json.loads((base / "tweets.json").read_text(encoding="utf-8"))
    assert {r["status_id"] for r in manifest} == {"1001", "1003"}
    assert (base / "tweets.jsonl").exists()
    assert (base / "latest-50.md").exists()
    assert (base / ".state" / "naval_x_scraper_state.json").exists()


def test_ingest_applies_multiline_quote_profile_for_rumi(tmp_path):
    mod = _load()
    hc_mod = _load("handle_config")
    rumi = next(h for h in hc_mod.HANDLES if h.name == "rumilyrics")

    items = [
        _apify_item("2001", "The wound is the place\nwhere the light enters you."),
        _apify_item("2002", " ".join(["a"] * 61)),
    ]
    result = mod.ingest(handle=rumi, vault_root=tmp_path, items=items)
    assert result.added == 2


def test_ingest_dedupes_within_handle_by_text_hash(tmp_path):
    mod = _load()
    hc_mod = _load("handle_config")
    naval = next(h for h in hc_mod.HANDLES if h.name == "naval")

    items = [
        _apify_item("3001", "Calm beats anxious."),
        _apify_item("3002", "calm beats   anxious."),
    ]
    result = mod.ingest(handle=naval, vault_root=tmp_path, items=items)
    assert result.added == 1


def test_ingest_dedupes_cross_handle_for_same_dedup_group(tmp_path):
    mod = _load()
    hc_mod = _load("handle_config")
    naval = next(h for h in hc_mod.HANDLES if h.name == "naval")
    nhq = next(h for h in hc_mod.HANDLES if h.name == "NavalismHQ")

    mod.ingest(handle=naval, vault_root=tmp_path, items=[
        _apify_item("4001", "Specific knowledge is taught."),
    ])
    result = mod.ingest(handle=nhq, vault_root=tmp_path, items=[
        _apify_item("4002", "Specific knowledge is taught."),
    ])
    assert result.added == 0
    nhq_manifest = tmp_path / "Library" / "X" / "NavalismHQ" / "tweets.json"
    assert json.loads(nhq_manifest.read_text(encoding="utf-8")) == []


def test_ingest_does_not_cross_dedup_across_groups(tmp_path):
    mod = _load()
    hc_mod = _load("handle_config")
    naval = next(h for h in hc_mod.HANDLES if h.name == "naval")
    rumi = next(h for h in hc_mod.HANDLES if h.name == "rumilyrics")

    mod.ingest(handle=naval, vault_root=tmp_path, items=[
        _apify_item("5001", "Calm beats anxious."),
    ])
    result = mod.ingest(handle=rumi, vault_root=tmp_path, items=[
        _apify_item("5002", "Calm beats anxious."),
    ])
    assert result.added == 1


def test_tweet_from_apify_item_tolerates_field_aliases(tmp_path):
    mod = _load()
    item = {
        "tweetId": "9001",
        "tweetUrl": "https://x.com/foo/status/9001",
        "full_text": "Hello world here.",
        "created_at": "2026-05-12T09:00:00.000Z",
        "isReply": False, "isRetweet": False, "isQuote": False, "media": [],
    }
    tweet = mod.tweet_from_apify_item(item, handle_name="foo")
    assert tweet is not None
    assert tweet.status_id == "9001"
    assert tweet.text == "Hello world here."
    assert tweet.x_url == "https://x.com/foo/status/9001"
