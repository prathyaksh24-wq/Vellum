# Naval X Apify Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken techtwitter scraper with an Apify-backed pipeline that captures only naval's aphorisms, polls every 15 min for new posts, and supports a one-shot 12-month backfill.

**Architecture:** Three new modules under `scripts/` — a thin Apify REST client, a pure aphorism filter, and a shared ingest core — plus two entry points (`scrape_naval_x.py` polling, `backfill_naval_x.py` one-shot). The Windows Task Scheduler trigger is swapped from daily 5am to every 15 min. CLAUDE.md Section 3 is broadened to allow the tweet-scraper actor.

**Tech Stack:** Python 3.11+ (`apify-client>=1.10.0` already a project dep), pytest, PowerShell + Windows Task Scheduler. Spec: `docs/superpowers/specs/2026-05-16-naval-x-apify-scraper-design.md`.

**File map:**
- Create: `scripts/aphorism_filter.py` — pure `is_aphorism(item)` function.
- Create: `scripts/apify_tweet_client.py` — thin wrapper over `apify-client`.
- Create: `scripts/naval_x_ingest.py` — manifest read, dedupe, write notes/indexes (extracted from existing `scrape_naval_x.py`).
- Rewrite: `scripts/scrape_naval_x.py` — polling entry point (was: techtwitter fetch + ingest).
- Create: `scripts/backfill_naval_x.py` — one-shot, paginates 12 months.
- Modify: `Vellum/CLAUDE.md` Section 3 — Apify usage rule broadened.
- Test: `backend/tests/test_aphorism_filter.py` — unit tests for the filter.
- Test: `backend/tests/test_naval_x_ingest.py` — ingest + dedupe tests.
- Test: `backend/tests/test_apify_tweet_client.py` — client builds correct input, parses response.

All script imports between modules use `importlib.util.spec_from_file_location` from tests (the existing pattern — see `test_youtube_importer.py`).

---

### Task 1: Aphorism filter — pure function

**Files:**
- Create: `scripts/aphorism_filter.py`
- Test: `backend/tests/test_aphorism_filter.py`

- [ ] **Step 1: Write the failing tests**

Write `backend/tests/test_aphorism_filter.py`:

```python
import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "aphorism_filter.py"


def _load():
    spec = importlib.util.spec_from_file_location("aphorism_filter", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _item(**overrides):
    base = {
        "text": "Play long-term games with long-term people.",
        "isRetweet": False,
        "isReply": False,
        "isQuote": False,
        "media": [],
    }
    base.update(overrides)
    return base


def test_short_standalone_wisdom_is_aphorism():
    af = _load()
    assert af.is_aphorism(_item()) is True


def test_retweet_rejected():
    af = _load()
    assert af.is_aphorism(_item(isRetweet=True)) is False


def test_reply_rejected():
    af = _load()
    assert af.is_aphorism(_item(isReply=True)) is False


def test_quote_tweet_rejected():
    af = _load()
    assert af.is_aphorism(_item(isQuote=True)) is False


def test_tweet_with_url_rejected():
    af = _load()
    assert af.is_aphorism(_item(text="Listen here: https://example.com/podcast")) is False


def test_tweet_with_media_rejected():
    af = _load()
    assert af.is_aphorism(_item(media=[{"type": "photo", "url": "x"}])) is False


def test_starts_with_mention_rejected():
    af = _load()
    assert af.is_aphorism(_item(text="@balajis good thread.")) is False


def test_podcast_toc_rejected_via_newlines():
    af = _load()
    text = "New podcast - Sell the Truth.\n00:00 Be Credible\n03:18 Yes, And\n04:31 Selfish Honesty"
    assert af.is_aphorism(_item(text=text)) is False


def test_long_tweet_over_max_chars_rejected():
    af = _load()
    assert af.is_aphorism(_item(text="a" * 281)) is False


def test_one_word_rejected():
    af = _load()
    assert af.is_aphorism(_item(text="Yes.")) is False


def test_sixty_one_words_rejected():
    af = _load()
    text = " ".join(["word"] * 61)
    assert af.is_aphorism(_item(text=text)) is False


def test_three_word_tweet_accepted():
    af = _load()
    assert af.is_aphorism(_item(text="Read, then write.")) is True


def test_four_sentences_rejected():
    af = _load()
    assert af.is_aphorism(_item(text="One. Two. Three. Four.")) is False


def test_three_sentences_accepted():
    af = _load()
    assert af.is_aphorism(_item(text="Read. Think. Write.")) is True


def test_empty_text_rejected():
    af = _load()
    assert af.is_aphorism(_item(text="")) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_aphorism_filter.py -v`
Expected: All tests FAIL — `scripts/aphorism_filter.py` does not exist yet.

- [ ] **Step 3: Implement `aphorism_filter.py`**

Write `scripts/aphorism_filter.py`:

```python
"""Aphorism classifier: rules-based filter over Apify tweet items."""
from __future__ import annotations

import re
from typing import Any

_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[.!?]+")

MAX_CHARS = 280
MIN_WORDS = 3
MAX_WORDS = 60
MAX_NEWLINES = 1
MAX_SENTENCES = 3


def is_aphorism(item: dict[str, Any]) -> bool:
    """Return True iff `item` is a short, standalone, wisdom-style tweet."""
    if item.get("isRetweet") or item.get("isReply") or item.get("isQuote"):
        return False

    text = (item.get("text") or "").strip()
    if not text:
        return False

    if len(text) > MAX_CHARS:
        return False

    if _URL_RE.search(text):
        return False

    if text.lstrip().startswith("@"):
        return False

    media = item.get("media") or []
    if media:
        return False

    if text.count("\n") > MAX_NEWLINES:
        return False

    sentences = [s for s in _SENTENCE_RE.split(text) if s.strip()]
    if len(sentences) > MAX_SENTENCES:
        return False

    words = text.split()
    if len(words) < MIN_WORDS or len(words) > MAX_WORDS:
        return False

    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_aphorism_filter.py -v`
Expected: All 15 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/aphorism_filter.py backend/tests/test_aphorism_filter.py
git commit -m "feat(naval-x): add aphorism filter for tweet classification"
```

---

### Task 2: Apify tweet client — thin wrapper

**Files:**
- Create: `scripts/apify_tweet_client.py`
- Test: `backend/tests/test_apify_tweet_client.py`

- [ ] **Step 1: Write the failing tests**

Write `backend/tests/test_apify_tweet_client.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_apify_tweet_client.py -v`
Expected: FAIL — `scripts/apify_tweet_client.py` does not exist.

- [ ] **Step 3: Implement `apify_tweet_client.py`**

Write `scripts/apify_tweet_client.py`:

```python
"""Thin wrapper around the Apify apidojo/tweet-scraper actor."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from apify_client import ApifyClient

ACTOR_ID = "apidojo~tweet-scraper"
DEFAULT_TIMEOUT_SECS = 120


def fetch_tweets(
    *,
    handle: str,
    start: datetime,
    end: datetime,
    max_items: int,
    token: str,
    timeout_secs: int = DEFAULT_TIMEOUT_SECS,
) -> list[dict[str, Any]]:
    """Run the tweet-scraper actor for `handle` between `start` and `end`.

    Returns the raw dataset items. Raises RuntimeError on actor failure.
    """
    client = ApifyClient(token)
    run_input = {
        "twitterHandles": [handle],
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "maxItems": max_items,
        "sort": "Latest",
        "tweetLanguage": "en",
    }
    run = client.actor(ACTOR_ID).call(run_input=run_input, timeout_secs=timeout_secs)
    if not run or not run.get("defaultDatasetId"):
        raise RuntimeError("Apify actor returned no dataset")
    dataset_id = run["defaultDatasetId"]
    return list(client.dataset(dataset_id).iterate_items())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_apify_tweet_client.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/apify_tweet_client.py backend/tests/test_apify_tweet_client.py
git commit -m "feat(naval-x): add Apify tweet-scraper client wrapper"
```

---

### Task 3: Ingest core — extract from existing scrape_naval_x.py

**Files:**
- Create: `scripts/naval_x_ingest.py`
- Test: `backend/tests/test_naval_x_ingest.py`

This task extracts the existing manifest / note / index logic from
`scripts/scrape_naval_x.py` into a reusable module and adds an Apify-item
mapper. The current `scrape_naval_x.py` stays functional during this task —
we modify it in Task 4.

- [ ] **Step 1: Write the failing tests**

Write `backend/tests/test_naval_x_ingest.py`:

```python
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

    items = [_apify_item("1001", "Fresh wisdom.")]
    result = mod.ingest(base=base, items=items)
    assert result.added == 1
    manifest = json.loads((base / "naval-tweets.json").read_text(encoding="utf-8"))
    ids = {row["status_id"] for row in manifest}
    assert ids == {"9000", "1001"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_naval_x_ingest.py -v`
Expected: FAIL — `scripts/naval_x_ingest.py` does not exist.

- [ ] **Step 3: Read existing scrape_naval_x.py to identify reusable functions**

Open `scripts/scrape_naval_x.py`. The functions to MOVE into `naval_x_ingest.py`:
- `Tweet` dataclass (lines 74–95)
- `snowflake_datetime` (115)
- `status_id_from_url` (120)
- `clean_text` (125)
- `slugify` (186)
- `yaml_quote` (191)
- `canonical_note_path` (195)
- `read_existing_manifest` (201)
- `existing_note_paths` (221)
- `tweet_from_record` (231)
- `note_markdown` (245)
- `write_tweet_note` (282)
- `normalize_existing_notes` (289)
- `record_for` (308)
- `wiki_link` (323)
- `write_latest` (327)
- `write_topic_indexes` (364)
- `write_year_indexes` (395)
- `write_agent_guide` (426)
- `write_root_index` (474)
- `write_manifests` (515)
- `write_state` (526)
- Constants: `HANDLE`, `X_EPOCH_MS`, `TOPIC_RULES`

These move verbatim. Functions that STAY in `scrape_naval_x.py` (rewritten in Task 4):
- `load_dotenv`, `vault_path`, `run`, `main`, `fetch_techtwitter` (DELETE), `is_original_text_tweet` (DELETE).

- [ ] **Step 4: Create `scripts/naval_x_ingest.py`**

Write `scripts/naval_x_ingest.py` with:

1. All the moved functions from Step 3 (copy verbatim from current
   `scrape_naval_x.py`, no signature changes).
2. Constants at top:

```python
HANDLE = "naval"
X_EPOCH_MS = 1288834974657
APIFY_SOURCE_LABEL = "Apify apidojo/tweet-scraper"
SOURCE_PROFILE_URL = f"https://x.com/{HANDLE}"
```

3. Replace `SOURCE_PROFILE`/`SOURCE_API` references in `write_root_index`
   with the X URL above only — drop the techtwitter API URL line.

4. Add a new mapper at the top of the module:

```python
def tweet_from_apify_item(item: dict) -> Tweet | None:
    """Convert an Apify dataset item to our Tweet dataclass.

    Accepts items shaped by `apidojo/tweet-scraper`. Tolerates field aliases
    (id/tweetId, createdAt/created_at, text/full_text, url/tweetUrl).
    """
    status_id = (
        item.get("id")
        or item.get("tweetId")
        or status_id_from_url(item.get("url") or item.get("tweetUrl") or "")
    )
    if not status_id:
        return None
    status_id = str(status_id)

    text = clean_text(item.get("text") or item.get("full_text"))
    if not text:
        return None

    created_raw = item.get("createdAt") or item.get("created_at")
    if created_raw:
        try:
            iso = created_raw.replace("Z", "+00:00")
            posted_utc = datetime.fromisoformat(iso).astimezone(timezone.utc).isoformat()
        except ValueError:
            posted_utc = snowflake_datetime(status_id).isoformat()
    else:
        posted_utc = snowflake_datetime(status_id).isoformat()

    x_url = item.get("url") or f"https://x.com/{HANDLE}/status/{status_id}"

    return Tweet(
        status_id=status_id,
        posted_utc=posted_utc,
        text=text,
        x_url=x_url,
        mirror_url=x_url,
        source=APIFY_SOURCE_LABEL,
    )
```

5. Add an `IngestResult` dataclass and `ingest()` function:

```python
@dataclass
class IngestResult:
    fetched: int
    filtered: int
    added: int
    total: int


def ingest(*, base: Path, items: list[dict]) -> IngestResult:
    """Filter, dedupe, persist. Returns counts."""
    # Lazy import to avoid coupling tests
    import importlib.util as _il
    _spec = _il.spec_from_file_location(
        "aphorism_filter", Path(__file__).parent / "aphorism_filter.py"
    )
    _af = _il.module_from_spec(_spec)
    _spec.loader.exec_module(_af)

    base.mkdir(parents=True, exist_ok=True)
    existing_records = read_existing_manifest(base)
    tweets_by_id: dict[str, Tweet] = {}
    for status_id, record in existing_records.items():
        t = tweet_from_record(record)
        if t:
            tweets_by_id[status_id] = t

    fetched = len(items)
    filtered = 0
    added = 0
    for item in items:
        if not _af.is_aphorism(item):
            filtered += 1
            continue
        tweet = tweet_from_apify_item(item)
        if not tweet:
            filtered += 1
            continue
        if tweet.status_id in tweets_by_id:
            continue
        tweets_by_id[tweet.status_id] = tweet
        added += 1

    tweets = sorted(tweets_by_id.values(), key=lambda t: t.posted_utc, reverse=True)
    captured_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for tweet in tweets:
        write_tweet_note(base, tweet, captured_utc)
    normalize_existing_notes(base, tweets_by_id, captured_utc)

    records = [record_for(tweet, base) for tweet in tweets]
    write_manifests(base, records)
    write_latest(base, records, captured_utc, limit=50)
    write_topic_indexes(base, records)
    write_year_indexes(base, records)
    write_agent_guide(base, records)
    write_root_index(base, records, captured_utc)
    write_state(base, fetched_count=fetched, added_count=added, total_count=len(records))

    return IngestResult(fetched=fetched, filtered=filtered, added=added, total=len(records))
```

Required imports at the top of `naval_x_ingest.py`:

```python
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from textwrap import shorten
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_naval_x_ingest.py -v`
Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/naval_x_ingest.py backend/tests/test_naval_x_ingest.py
git commit -m "feat(naval-x): extract reusable ingest core with Apify mapper"
```

---

### Task 4: Rewrite scrape_naval_x.py as polling entry point

**Files:**
- Modify: `scripts/scrape_naval_x.py` (full rewrite)

- [ ] **Step 1: Read existing state-file format**

Read `Vault/X/naval/.state/naval_x_scraper_state.json` and confirm shape:
```json
{
  "last_run_utc": "2026-05-14T03:12:11+00:00",
  "handle": "naval",
  "fetched_count": 48,
  "added_count": 0,
  "total_count": 50
}
```

The polling script uses `last_run_utc` as the lower bound of the next fetch window (with a 2-hour cushion).

- [ ] **Step 2: Replace `scripts/scrape_naval_x.py` with the polling entry point**

```python
#!/usr/bin/env python3
"""Poll Apify for naval's latest tweets and ingest aphorisms into the vault."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HANDLE = "naval"
DEFAULT_WINDOW_HOURS = 2
DEFAULT_MAX_ITEMS = 200


def _load(name: str):
    path = Path(__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def vault_path(project_root: Path) -> Path:
    load_dotenv(project_root / ".env")
    configured = os.environ.get("OBSIDIAN_VAULT_PATH")
    return Path(configured) if configured else project_root / "Vault"


def read_state(state_file: Path) -> dict:
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def compute_window(state: dict, window_hours: int, now: datetime) -> tuple[datetime, datetime]:
    """Lower bound: max(last_run - cushion, now - 14 days). Upper: now."""
    cushion = timedelta(hours=window_hours)
    last_run_iso = state.get("last_run_utc")
    if last_run_iso:
        try:
            last_run = datetime.fromisoformat(last_run_iso)
        except ValueError:
            last_run = now - timedelta(days=1)
    else:
        last_run = now - timedelta(days=1)
    start = max(last_run - cushion, now - timedelta(days=14))
    return start, now


def run(project_root: Path, dry_run: bool, max_items: int, window_hours: int) -> int:
    vault = vault_path(project_root)
    base = vault / "X" / HANDLE
    state_file = base / ".state" / "naval_x_scraper_state.json"

    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        print("APIFY_API_TOKEN missing from environment", file=sys.stderr)
        return 3

    state = read_state(state_file)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start, end = compute_window(state, window_hours, now)

    client = _load("apify_tweet_client")
    ingest_mod = _load("naval_x_ingest")

    try:
        items = client.fetch_tweets(
            handle=HANDLE,
            start=start,
            end=end,
            max_items=max_items,
            token=token,
        )
    except Exception as exc:
        print(f"Apify fetch failed: {exc}", file=sys.stderr)
        return 2

    if dry_run:
        print(json.dumps({
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "fetched": len(items),
        }, indent=2))
        return 0

    result = ingest_mod.ingest(base=base, items=items)
    print(
        f"Fetched {result.fetched}, filtered {result.filtered}, "
        f"added {result.added}, total {result.total}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    parser.add_argument("--window-hours", type=int, default=DEFAULT_WINDOW_HOURS)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    try:
        return run(args.project_root.resolve(), args.dry_run, args.max_items, args.window_hours)
    except Exception as exc:
        print(f"naval polling failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Smoke test (live Apify) — dry run**

Run from project root:

```bash
cd "c:/Users/User/OneDrive/Desktop/Vellum/Vellum"
.venv/Scripts/python.exe scripts/scrape_naval_x.py --dry-run
```

Expected output: JSON with `window_start`, `window_end`, `fetched: <int>`.
Non-zero `fetched` means live Apify works. Exit code 0.

If `APIFY_API_TOKEN missing` (exit 3): confirm `.env` has the token.
If `Apify fetch failed` (exit 2): inspect the message — usually means the
actor input was rejected (4xx) or the token is invalid.

- [ ] **Step 4: Smoke test — real ingest (small window)**

Run:

```bash
.venv/Scripts/python.exe scripts/scrape_naval_x.py --window-hours 168
```

Expected: stdout line `Fetched X, filtered Y, added Z, total N`. The
state file `Vault/X/naval/.state/naval_x_scraper_state.json` is updated
with current `last_run_utc`. New tweet markdown files (if any aphorisms
were captured) appear under `Vault/X/naval/tweets/2026/`. `latest-50.md`
regenerated.

- [ ] **Step 5: Commit**

```bash
git add scripts/scrape_naval_x.py
git commit -m "feat(naval-x): rewrite polling entry point on Apify"
```

---

### Task 5: One-shot backfill script

**Files:**
- Create: `scripts/backfill_naval_x.py`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""One-shot: backfill naval's aphorisms for the last 12 months."""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HANDLE = "naval"
BACKFILL_MONTHS = 12
MAX_ITEMS_PER_MONTH = 1000
INTER_REQUEST_SLEEP_SECS = 2


def _load(name: str):
    path = Path(__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def vault_path(project_root: Path) -> Path:
    load_dotenv(project_root / ".env")
    configured = os.environ.get("OBSIDIAN_VAULT_PATH")
    return Path(configured) if configured else project_root / "Vault"


def month_windows(now: datetime, months: int) -> list[tuple[datetime, datetime]]:
    """Yield (start, end) pairs walking back `months` calendar months."""
    windows = []
    end = now
    for _ in range(months):
        start = end - timedelta(days=30)
        windows.append((start, end))
        end = start
    return list(reversed(windows))


def run(project_root: Path, months: int, max_per_window: int) -> int:
    vault = vault_path(project_root)
    base = vault / "X" / HANDLE
    base.mkdir(parents=True, exist_ok=True)

    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        print("APIFY_API_TOKEN missing from environment", file=sys.stderr)
        return 3

    client = _load("apify_tweet_client")
    ingest_mod = _load("naval_x_ingest")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    windows = month_windows(now, months)

    total_fetched = 0
    total_added = 0
    total_filtered = 0
    for start, end in windows:
        try:
            items = client.fetch_tweets(
                handle=HANDLE,
                start=start,
                end=end,
                max_items=max_per_window,
                token=token,
            )
        except Exception as exc:
            print(f"Window {start.date()}..{end.date()} failed: {exc}", file=sys.stderr)
            continue

        result = ingest_mod.ingest(base=base, items=items)
        total_fetched += result.fetched
        total_filtered += result.filtered
        total_added += result.added
        print(
            f"Window {start.date()}..{end.date()}: fetched {result.fetched}, "
            f"filtered {result.filtered}, added {result.added}"
        )
        time.sleep(INTER_REQUEST_SLEEP_SECS)

    print(
        f"\nBackfill done. Total fetched {total_fetched}, "
        f"filtered {total_filtered}, added {total_added}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=BACKFILL_MONTHS)
    parser.add_argument("--max-per-window", type=int, default=MAX_ITEMS_PER_MONTH)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    try:
        return run(args.project_root.resolve(), args.months, args.max_per_window)
    except Exception as exc:
        print(f"naval backfill failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Commit**

```bash
git add scripts/backfill_naval_x.py
git commit -m "feat(naval-x): add one-shot 12-month backfill script"
```

- [ ] **Step 3: User manually runs the backfill**

User runs once, from project root:

```bash
cd "c:/Users/User/OneDrive/Desktop/Vellum/Vellum"
.venv/Scripts/python.exe scripts/backfill_naval_x.py
```

Expected: ~12 lines of `Window YYYY-MM-DD..YYYY-MM-DD: fetched X, filtered Y, added Z`, then a totals line. Apify dashboard will show ~12 actor runs. Total cost on Apify dashboard should be < $1.

After this completes, `Vault/X/naval/tweets/YYYY/` is populated, `latest-50.md` reflects the most recent 50 aphorisms, and `naval-tweets.jsonl` is the full archive.

---

### Task 6: Update CLAUDE.md — broaden Apify allowlist

**Files:**
- Modify: `Vellum/CLAUDE.md` (Section 3, the `**Apify MCP**` block)

- [ ] **Step 1: Edit CLAUDE.md**

In `c:/Users/User/OneDrive/Desktop/Vellum/Vellum/CLAUDE.md`, find the block
that starts with:

```
**Apify MCP** (via `https://mcp.apify.com/sse`)
- Used for: Amazon product scraper only
```

Replace that block with:

```
**Apify (REST API for scheduled ingestion + MCP for agent calls)**
- REST API used by scheduled scrapers (Amazon, X tweet archive) with `APIFY_API_TOKEN`.
- MCP (`https://mcp.apify.com/sse`) used for agent-driven scraping (Amazon product lookups).
- Output is ALWAYS stored locally first, THEN scrubbed if YELLOW, THEN
  summarized before the LLM sees any of it.
- Never used as a general web scraper without explicit user instruction.
```

- [ ] **Step 2: Commit**

```bash
git add Vellum/CLAUDE.md
git commit -m "docs(claude): broaden Apify rule to allow X tweet archive ingestion"
```

---

### Task 7: Switch Windows Task Scheduler to 15-minute polling

**Files:** none (Windows Task Scheduler configuration only).

This is an operational task. The script content (`run_naval_x_scrape.ps1`) is unchanged — only the trigger schedule.

- [ ] **Step 1: Identify the existing task name**

Run in PowerShell:

```powershell
Get-ScheduledTask | Where-Object { $_.TaskName -like "*naval*" -or $_.Actions.Arguments -like "*run_naval_x_scrape*" } | Format-Table TaskName, TaskPath
```

Note the `TaskName` (e.g., `NavalXScrape`). If no matching task exists, the daily 5am task may live under a different name — list all and inspect:

```powershell
Get-ScheduledTask | Where-Object { $_.Actions.Arguments -like "*run_naval_x_scrape*" } | Format-List TaskName, TaskPath
```

- [ ] **Step 2: Delete the old daily task**

Substitute `<TaskName>` with the name from Step 1:

```powershell
Unregister-ScheduledTask -TaskName "<TaskName>" -Confirm:$false
```

- [ ] **Step 3: Register the new 15-minute task**

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"c:\Users\User\OneDrive\Desktop\Vellum\Vellum\scripts\run_naval_x_scrape.ps1`""

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "NavalXPoller" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "Polls Apify every 15 min for naval aphorisms" `
    -User "$env:USERNAME" -RunLevel Limited
```

`StartWhenAvailable` means missed runs (PC off / asleep) catch up on next boot. `MultipleInstances IgnoreNew` means if a run takes >15 min, the next trigger is skipped rather than stacking.

- [ ] **Step 4: Verify the task runs**

Force the task once and then check the log:

```powershell
Start-ScheduledTask -TaskName "NavalXPoller"
Start-Sleep -Seconds 30
Get-Content "c:\Users\User\OneDrive\Desktop\Vellum\Vellum\data\logs\naval-x-scrape.log" -Tail 10
```

Expected: a "Starting @naval X scrape" line, an Apify-driven `Fetched X, filtered Y, added Z, total N` line, then "Finished @naval X scrape with exit code 0".

- [ ] **Step 5: Final verification — confirm next-trigger time**

```powershell
Get-ScheduledTaskInfo -TaskName "NavalXPoller" | Format-List LastRunTime, NextRunTime, LastTaskResult
```

Expected: `LastTaskResult: 0` and `NextRunTime` ~15 min in the future.

---

## Self-Review

**Spec coverage:**
- Goal 1 (Apify, no X dev account): Task 2, 4, 5.
- Goal 2 (aphorism filter): Task 1.
- Goal 3 (15-min polling): Task 4 + Task 7.
- Goal 4 (one-shot 12-mo backfill): Task 5.
- Goal 5 (preserve vault layout): Task 3 (ingest core extracted unchanged).
- CLAUDE.md update: Task 6.
- All failure-mode exit codes: implemented in Task 4 (`return 2/3` paths).

**Placeholder scan:** No `TBD`, `TODO`, `implement later`, or "similar to Task N" references. All code blocks present.

**Type consistency:** `Tweet` dataclass shape and `IngestResult` fields (`fetched`, `filtered`, `added`, `total`) match across Task 3, 4, 5 and the tests in Task 3.

**Notes for the executor:**
- Run all `pytest` commands from `c:/Users/User/OneDrive/Desktop/Vellum/Vellum/backend/`.
- All Python scripts must be runnable from project root (`c:/Users/User/OneDrive/Desktop/Vellum/Vellum/`).
- The existing `Vault/X/naval/.state/naval_x_scraper_state.json` continues to work — its schema is unchanged.
