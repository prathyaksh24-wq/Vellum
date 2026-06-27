# Multi-Handle X Quotes Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize the naval-only X scraper into a 4-handle pipeline (naval, NavalismHQ, rumilyrics, AlexHormozi) with per-handle filter profiles, text-hash dedup (within + cross-handle), monthly Apify budget ceiling at $5, and a 6-hour polling cadence — all under `Vault/Library/X/<handle>/`.

**Architecture:** Refactor the naval-specific modules into a handle-agnostic core driven by a `HandleConfig` registry. New filter-profile module replaces the strict aphorism filter with three named profiles. New dedup module computes normalized text hashes and checks both within-handle and cross-handle scope. New budget module tracks monthly Apify spend, warns at $4.50, refuses calls at $5.00.

**Tech Stack:** Python 3.11+ (`apify-client>=1.10.0` already a project dep), pytest, PowerShell + Windows Task Scheduler. Spec: `docs/superpowers/specs/2026-05-16-multi-handle-x-quotes-design.md`. Branch: `feat/multi-handle-x`.

**File map (creates):**
- `scripts/filter_profiles.py` — three filter functions registered by name
- `scripts/handle_config.py` — `HandleConfig` dataclass + `HANDLES` registry + `vault_base_for(handle, vault)` helper
- `scripts/x_dedup.py` — text-hash + within/cross-handle dedup helpers
- `scripts/x_budget.py` — monthly ledger at `data/apify-budget.json`
- `scripts/x_ingest.py` — handle-agnostic ingest core
- `scripts/poll_x.py` — polling driver (all handles in one run)
- `scripts/backfill_x.py` — one-shot backfill (`--all` or `--handle`)
- `scripts/run_x_poll.ps1` — PowerShell wrapper for the scheduled task
- `scripts/migrate_naval_filenames.py` — one-shot rename of naval manifest filenames
- `backend/tests/test_filter_profiles.py`
- `backend/tests/test_handle_config.py`
- `backend/tests/test_x_dedup.py`
- `backend/tests/test_x_budget.py`
- `backend/tests/test_x_ingest.py`

**File map (deletes after new code is verified):**
- `scripts/aphorism_filter.py`
- `scripts/naval_x_ingest.py`
- `scripts/scrape_naval_x.py`
- `scripts/backfill_naval_x.py`
- `scripts/run_naval_x_scrape.ps1`
- `backend/tests/test_aphorism_filter.py`
- `backend/tests/test_naval_x_ingest.py`

**File map (modifies):**
- `Vellum/CLAUDE.md` — folder-policy exception clause: `X/` → `Library/X/` (line ~531)

**Operational:**
- Run `scripts/migrate_naval_filenames.py` once after Task 6.
- Unregister Windows Task `NavalXPoller` (currently disabled), register `XPoller` (every 6h) at Task 11.

**Reusing existing code:**
- `scripts/apify_tweet_client.py` stays as-is — already handle-agnostic.
- `backend/tests/test_apify_tweet_client.py` stays as-is — passes unchanged.

**Path conventions:**
- All `scripts/` files use `importlib.util.spec_from_file_location` to load siblings (project convention). Loader pattern includes `sys.modules[name] = module` for Python 3.14 dataclass resolution.
- All entry-point scripts also use a `load_dotenv(project_root / ".env")` helper.

---

### Task 1: Filter profiles

**Files:**
- Create: `scripts/filter_profiles.py`
- Test: `backend/tests/test_filter_profiles.py`

- [ ] **Step 1: Write the failing tests**

Write `backend/tests/test_filter_profiles.py`:

```python
import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "filter_profiles.py"


def _load():
    spec = importlib.util.spec_from_file_location("filter_profiles", SCRIPT_PATH)
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


# ---- aphorism profile (carries the prior 15 cases) ----

def test_aphorism_accepts_short_wisdom():
    fp = _load()
    assert fp.accepts("aphorism", _item()) is True

def test_aphorism_rejects_retweet():
    fp = _load()
    assert fp.accepts("aphorism", _item(isRetweet=True)) is False

def test_aphorism_rejects_reply():
    fp = _load()
    assert fp.accepts("aphorism", _item(isReply=True)) is False

def test_aphorism_rejects_quote_tweet():
    fp = _load()
    assert fp.accepts("aphorism", _item(isQuote=True)) is False

def test_aphorism_rejects_url():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="Read: https://example.com")) is False

def test_aphorism_rejects_media():
    fp = _load()
    assert fp.accepts("aphorism", _item(media=[{"type": "photo"}])) is False

def test_aphorism_rejects_mention_start():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="@bob hi.")) is False

def test_aphorism_rejects_multi_newline():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="One.\nTwo.\nThree.")) is False

def test_aphorism_rejects_over_280_chars():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="a" * 281)) is False

def test_aphorism_rejects_one_word():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="Yes.")) is False

def test_aphorism_rejects_61_words():
    fp = _load()
    assert fp.accepts("aphorism", _item(text=" ".join(["w"] * 61))) is False

def test_aphorism_rejects_4_sentences():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="One. Two. Three. Four.")) is False

def test_aphorism_accepts_3_sentences():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="Read. Think. Write.")) is True

def test_aphorism_accepts_three_words():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="Stay. Be. Become.")) is True

def test_aphorism_rejects_empty():
    fp = _load()
    assert fp.accepts("aphorism", _item(text="")) is False


# ---- multiline_quote profile ----

def test_multiline_quote_accepts_couplet():
    fp = _load()
    text = "The wound is the place\nwhere the light enters you."
    assert fp.accepts("multiline_quote", _item(text=text)) is True

def test_multiline_quote_accepts_10_lines():
    fp = _load()
    text = "\n".join(["line one"] * 11)  # 11 lines = 10 newlines
    assert fp.accepts("multiline_quote", _item(text=text)) is True

def test_multiline_quote_rejects_11_newlines():
    fp = _load()
    text = "\n".join(["line"] * 12)  # 11 newlines
    assert fp.accepts("multiline_quote", _item(text=text)) is False

def test_multiline_quote_rejects_over_500_chars():
    fp = _load()
    assert fp.accepts("multiline_quote", _item(text="a" * 501)) is False

def test_multiline_quote_rejects_url():
    fp = _load()
    assert fp.accepts("multiline_quote", _item(text="Wisdom\nhttp://x.com/y")) is False

def test_multiline_quote_rejects_media():
    fp = _load()
    assert fp.accepts("multiline_quote", _item(media=[{"type": "photo"}])) is False

def test_multiline_quote_rejects_retweet():
    fp = _load()
    assert fp.accepts("multiline_quote", _item(isRetweet=True)) is False

def test_multiline_quote_rejects_too_short():
    fp = _load()
    assert fp.accepts("multiline_quote", _item(text="So")) is False


# ---- original_tweet profile (Hormozi-style mini-essays) ----

def test_original_tweet_accepts_long_essay():
    fp = _load()
    text = ("Most people overestimate what they can do in a day\n"
            "and underestimate what they can do in a year.\n"
            "Stack small wins. Compound never fails. Win the decade by winning today.")
    assert fp.accepts("original_tweet", _item(text=text)) is True

def test_original_tweet_rejects_under_10_words():
    fp = _load()
    assert fp.accepts("original_tweet", _item(text="One two three four five six seven eight nine.")) is False

def test_original_tweet_rejects_url():
    fp = _load()
    assert fp.accepts("original_tweet", _item(text="long enough wisdom https://example.com extra words")) is False

def test_original_tweet_rejects_retweet():
    fp = _load()
    long = " ".join(["word"] * 20)
    assert fp.accepts("original_tweet", _item(text=long, isRetweet=True)) is False

def test_original_tweet_rejects_reply():
    fp = _load()
    long = " ".join(["word"] * 20)
    assert fp.accepts("original_tweet", _item(text=long, isReply=True)) is False

def test_original_tweet_rejects_media():
    fp = _load()
    long = " ".join(["word"] * 20)
    assert fp.accepts("original_tweet", _item(text=long, media=[{"type": "photo"}])) is False


# ---- registry ----

def test_unknown_profile_raises():
    fp = _load()
    import pytest
    with pytest.raises(KeyError):
        fp.accepts("nonexistent_profile", _item())

def test_profiles_registry_lists_three():
    fp = _load()
    assert set(fp.PROFILES.keys()) == {"aphorism", "multiline_quote", "original_tweet"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `backend/`:
`c:/Users/User/OneDrive/Desktop/Vellum/Vellum/.venv/Scripts/python.exe -m pytest tests/test_filter_profiles.py -v`
Expected: FAIL — `scripts/filter_profiles.py` does not exist.

- [ ] **Step 3: Implement `filter_profiles.py`**

Write `scripts/filter_profiles.py`:

```python
"""Filter profiles for X tweet ingestion.

Each profile is a pure boolean function over an Apify item dict.
Register a profile in `PROFILES` and dispatch via `accepts(profile_name, item)`.
"""
from __future__ import annotations

import re
from typing import Any, Callable

_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[.!?]+")


def _is_original(item: dict[str, Any]) -> bool:
    """Common rejection rules: must be an original tweet, no media."""
    if item.get("isRetweet") or item.get("isReply") or item.get("isQuote"):
        return False
    if item.get("media") or []:
        return False
    return True


def _text(item: dict[str, Any]) -> str:
    return (item.get("text") or "").strip()


def _aphorism(item: dict[str, Any]) -> bool:
    if not _is_original(item):
        return False
    text = _text(item)
    if not text:
        return False
    if len(text) > 280:
        return False
    if _URL_RE.search(text):
        return False
    if text.lstrip().startswith("@"):
        return False
    if text.count("\n") > 1:
        return False
    sentences = [s for s in _SENTENCE_RE.split(text) if s.strip()]
    if len(sentences) > 3:
        return False
    words = text.split()
    if len(words) < 3 or len(words) > 60:
        return False
    return True


def _multiline_quote(item: dict[str, Any]) -> bool:
    if not _is_original(item):
        return False
    text = _text(item)
    if not text:
        return False
    if len(text) > 500:
        return False
    if _URL_RE.search(text):
        return False
    if text.lstrip().startswith("@"):
        return False
    if text.count("\n") > 10:
        return False
    words = text.split()
    if len(words) < 3:
        return False
    return True


def _original_tweet(item: dict[str, Any]) -> bool:
    if not _is_original(item):
        return False
    text = _text(item)
    if not text:
        return False
    if _URL_RE.search(text):
        return False
    words = text.split()
    if len(words) < 10:
        return False
    return True


PROFILES: dict[str, Callable[[dict[str, Any]], bool]] = {
    "aphorism": _aphorism,
    "multiline_quote": _multiline_quote,
    "original_tweet": _original_tweet,
}


def accepts(profile_name: str, item: dict[str, Any]) -> bool:
    """Return True iff `item` passes the named filter profile."""
    if profile_name not in PROFILES:
        raise KeyError(f"Unknown filter profile: {profile_name}")
    return PROFILES[profile_name](item)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `c:/Users/User/OneDrive/Desktop/Vellum/Vellum/.venv/Scripts/python.exe -m pytest tests/test_filter_profiles.py -v` from `backend/`
Expected: all 30 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd "c:/Users/User/OneDrive/Desktop/Vellum/Vellum"
git add scripts/filter_profiles.py backend/tests/test_filter_profiles.py
git commit -m "feat(x): filter profiles registry (aphorism/multiline_quote/original_tweet)"
```

---

### Task 2: Handle config

**Files:**
- Create: `scripts/handle_config.py`
- Test: `backend/tests/test_handle_config.py`

- [ ] **Step 1: Write the failing tests**

Write `backend/tests/test_handle_config.py`:

```python
import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "handle_config.py"


def _load():
    spec = importlib.util.spec_from_file_location("handle_config", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_handles_registry_has_four_handles():
    mod = _load()
    names = [h.name for h in mod.HANDLES]
    assert names == ["naval", "NavalismHQ", "rumilyrics", "AlexHormozi"]


def test_handles_have_no_duplicate_names():
    mod = _load()
    names = [h.name for h in mod.HANDLES]
    assert len(names) == len(set(names))


def test_naval_and_navalismhq_share_dedup_group():
    mod = _load()
    by_name = {h.name: h for h in mod.HANDLES}
    assert by_name["naval"].dedup_group == "naval"
    assert by_name["NavalismHQ"].dedup_group == "naval"


def test_rumi_and_hormozi_have_isolated_dedup_groups():
    mod = _load()
    by_name = {h.name: h for h in mod.HANDLES}
    assert by_name["rumilyrics"].dedup_group == "rumi"
    assert by_name["AlexHormozi"].dedup_group == "hormozi"


def test_filter_profiles_assigned_correctly():
    mod = _load()
    by_name = {h.name: h for h in mod.HANDLES}
    assert by_name["naval"].filter_profile == "aphorism"
    assert by_name["NavalismHQ"].filter_profile == "aphorism"
    assert by_name["rumilyrics"].filter_profile == "multiline_quote"
    assert by_name["AlexHormozi"].filter_profile == "original_tweet"


def test_vault_base_for_returns_library_path(tmp_path):
    mod = _load()
    h = mod.HandleConfig(
        name="naval",
        filter_profile="aphorism",
        dedup_group="naval",
        source_label="Apify apidojo/tweet-scraper",
    )
    base = mod.vault_base_for(h, tmp_path)
    assert base == tmp_path / "Library" / "X" / "naval"


def test_vault_base_preserves_case():
    mod = _load()
    h = mod.HandleConfig(
        name="NavalismHQ",
        filter_profile="aphorism",
        dedup_group="naval",
        source_label="x",
    )
    base = mod.vault_base_for(h, Path("/v"))
    assert base.name == "NavalismHQ"


def test_handles_in_dedup_group_returns_siblings():
    mod = _load()
    siblings = mod.handles_in_dedup_group("naval")
    names = sorted(h.name for h in siblings)
    assert names == ["NavalismHQ", "naval"]


def test_handles_in_dedup_group_for_solo_handle():
    mod = _load()
    siblings = mod.handles_in_dedup_group("hormozi")
    assert [h.name for h in siblings] == ["AlexHormozi"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_handle_config.py -v` from `backend/`
Expected: FAIL — `scripts/handle_config.py` does not exist.

- [ ] **Step 3: Implement `handle_config.py`**

Write `scripts/handle_config.py`:

```python
"""Handle configuration registry for multi-handle X scraping."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


APIFY_SOURCE_LABEL = "Apify apidojo/tweet-scraper"


@dataclass(frozen=True)
class HandleConfig:
    name: str             # X handle, case preserved (e.g. "NavalismHQ")
    filter_profile: str   # key into filter_profiles.PROFILES
    dedup_group: str      # cross-handle dedup scope
    source_label: str     # for tweet frontmatter


HANDLES: list[HandleConfig] = [
    HandleConfig(name="naval",       filter_profile="aphorism",        dedup_group="naval",   source_label=APIFY_SOURCE_LABEL),
    HandleConfig(name="NavalismHQ",  filter_profile="aphorism",        dedup_group="naval",   source_label=APIFY_SOURCE_LABEL),
    HandleConfig(name="rumilyrics",  filter_profile="multiline_quote", dedup_group="rumi",    source_label=APIFY_SOURCE_LABEL),
    HandleConfig(name="AlexHormozi", filter_profile="original_tweet",  dedup_group="hormozi", source_label=APIFY_SOURCE_LABEL),
]


def vault_base_for(handle: HandleConfig, vault_root: Path) -> Path:
    """Return the per-handle vault folder under Library/X/."""
    return vault_root / "Library" / "X" / handle.name


def handles_in_dedup_group(group: str) -> list[HandleConfig]:
    """Return every configured handle in the named dedup group."""
    return [h for h in HANDLES if h.dedup_group == group]


def get_handle(name: str) -> HandleConfig:
    """Lookup a handle by its name. Raises KeyError if not found."""
    for h in HANDLES:
        if h.name == name:
            return h
    raise KeyError(f"Unknown handle: {name}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_handle_config.py -v` from `backend/`
Expected: 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/handle_config.py backend/tests/test_handle_config.py
git commit -m "feat(x): HandleConfig registry + vault path helper"
```

---

### Task 3: Text-hash dedup

**Files:**
- Create: `scripts/x_dedup.py`
- Test: `backend/tests/test_x_dedup.py`

- [ ] **Step 1: Write the failing tests**

Write `backend/tests/test_x_dedup.py`:

```python
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "x_dedup.py"


def _load():
    spec = importlib.util.spec_from_file_location("x_dedup", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_text_hash_lowercases_and_collapses_whitespace():
    mod = _load()
    h1 = mod.text_hash("Be honest with yourself.")
    h2 = mod.text_hash("be honest   with yourself.")
    assert h1 == h2


def test_text_hash_preserves_punctuation():
    mod = _load()
    h1 = mod.text_hash("Be present.")
    h2 = mod.text_hash("Be present")
    assert h1 != h2


def test_text_hash_returns_16_hex_chars():
    mod = _load()
    h = mod.text_hash("anything")
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_load_text_hashes_returns_empty_for_missing_manifest(tmp_path):
    mod = _load()
    base = tmp_path / "X" / "naval"
    base.mkdir(parents=True)
    hashes = mod.load_text_hashes(base)
    assert hashes == set()


def test_load_text_hashes_reads_existing_manifest(tmp_path):
    mod = _load()
    base = tmp_path / "X" / "naval"
    base.mkdir(parents=True)
    records = [
        {"status_id": "1", "text_hash": "abc1234567890def"},
        {"status_id": "2", "text_hash": "1234567890abcdef"},
    ]
    (base / "tweets.json").write_text(json.dumps(records), encoding="utf-8")
    hashes = mod.load_text_hashes(base)
    assert hashes == {"abc1234567890def", "1234567890abcdef"}


def test_collect_group_text_hashes_unions_siblings(tmp_path):
    mod = _load()
    naval = tmp_path / "Library" / "X" / "naval"
    nhq = tmp_path / "Library" / "X" / "NavalismHQ"
    naval.mkdir(parents=True)
    nhq.mkdir(parents=True)
    (naval / "tweets.json").write_text(
        json.dumps([{"status_id": "n1", "text_hash": "aaaa111122223333"}]),
        encoding="utf-8",
    )
    (nhq / "tweets.json").write_text(
        json.dumps([{"status_id": "h1", "text_hash": "bbbb444455556666"}]),
        encoding="utf-8",
    )

    # Use a stub handle list to avoid coupling to handle_config
    class _H:
        def __init__(self, name): self.name = name
    handles = [_H("naval"), _H("NavalismHQ")]

    hashes = mod.collect_group_text_hashes(
        handles=handles, vault_root=tmp_path, exclude_name="rumilyrics"
    )
    assert hashes == {"aaaa111122223333", "bbbb444455556666"}


def test_collect_group_text_hashes_excludes_self(tmp_path):
    mod = _load()
    naval = tmp_path / "Library" / "X" / "naval"
    nhq = tmp_path / "Library" / "X" / "NavalismHQ"
    naval.mkdir(parents=True)
    nhq.mkdir(parents=True)
    (naval / "tweets.json").write_text(
        json.dumps([{"status_id": "n1", "text_hash": "aaaa"}]),
        encoding="utf-8",
    )
    (nhq / "tweets.json").write_text(
        json.dumps([{"status_id": "h1", "text_hash": "bbbb"}]),
        encoding="utf-8",
    )

    class _H:
        def __init__(self, name): self.name = name
    handles = [_H("naval"), _H("NavalismHQ")]

    hashes = mod.collect_group_text_hashes(
        handles=handles, vault_root=tmp_path, exclude_name="naval"
    )
    # naval excluded, only NavalismHQ contributes
    assert hashes == {"bbbb"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_x_dedup.py -v` from `backend/`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `x_dedup.py`**

Write `scripts/x_dedup.py`:

```python
"""Text-hash dedup for X handles, both within-handle and cross-handle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


def text_hash(text: str) -> str:
    """Normalize and hash tweet text. 16 hex chars of SHA-256.

    Normalization: lowercase, whitespace-collapsed. Punctuation kept.
    """
    normalized = " ".join((text or "").lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def load_text_hashes(base: Path) -> set[str]:
    """Read the handle's manifest and return the set of text_hash values.

    Returns empty set if the manifest doesn't exist or is malformed.
    """
    manifest = base / "tweets.json"
    if not manifest.exists():
        return set()
    try:
        records = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return {row["text_hash"] for row in records if row.get("text_hash")}


def collect_group_text_hashes(
    *,
    handles: Iterable,
    vault_root: Path,
    exclude_name: str,
) -> set[str]:
    """Union the text_hash sets from every handle in `handles` whose name
    is not `exclude_name`. Used to compute the cross-handle dedup set."""
    out: set[str] = set()
    for h in handles:
        if h.name == exclude_name:
            continue
        base = vault_root / "Library" / "X" / h.name
        out |= load_text_hashes(base)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_x_dedup.py -v` from `backend/`
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/x_dedup.py backend/tests/test_x_dedup.py
git commit -m "feat(x): text-hash dedup helpers (within and cross-handle)"
```

---

### Task 4: Apify budget ledger

**Files:**
- Create: `scripts/x_budget.py`
- Test: `backend/tests/test_x_budget.py`

- [ ] **Step 1: Write the failing tests**

Write `backend/tests/test_x_budget.py`:

```python
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "x_budget.py"


def _load():
    spec = importlib.util.spec_from_file_location("x_budget", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_record_creates_monthly_bucket(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    bookkeeper = mod.BudgetLedger(ledger_path, month="2026-05")
    bookkeeper.record(handle="naval", run_usd=0.50)
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert "2026-05" in data
    assert data["2026-05"]["used_usd"] == 0.50
    assert len(data["2026-05"]["runs"]) == 1
    assert data["2026-05"]["runs"][0]["handle"] == "naval"


def test_record_accumulates_within_month(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    b = mod.BudgetLedger(ledger_path, month="2026-05")
    b.record(handle="naval", run_usd=0.30)
    b.record(handle="NavalismHQ", run_usd=0.20)
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert data["2026-05"]["used_usd"] == 0.50
    assert len(data["2026-05"]["runs"]) == 2


def test_new_month_starts_fresh(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    mod.BudgetLedger(ledger_path, month="2026-05").record(handle="naval", run_usd=4.90)
    mod.BudgetLedger(ledger_path, month="2026-06").record(handle="naval", run_usd=0.10)
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert data["2026-05"]["used_usd"] == 4.90
    assert data["2026-06"]["used_usd"] == 0.10


def test_used_returns_current_month_total(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    b = mod.BudgetLedger(ledger_path, month="2026-05")
    assert b.used() == 0.0
    b.record(handle="naval", run_usd=1.25)
    assert b.used() == 1.25


def test_pre_call_check_passes_under_cap(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    b = mod.BudgetLedger(ledger_path, month="2026-05")
    b.record(handle="naval", run_usd=4.49)
    b.pre_call_check()  # must not raise


def test_pre_call_check_raises_at_or_above_cap(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    b = mod.BudgetLedger(ledger_path, month="2026-05")
    b.record(handle="naval", run_usd=5.00)
    import pytest
    with pytest.raises(mod.BudgetExhausted):
        b.pre_call_check()


def test_near_cap_threshold(tmp_path):
    mod = _load()
    ledger_path = tmp_path / "apify-budget.json"
    b = mod.BudgetLedger(ledger_path, month="2026-05")
    assert b.near_cap() is False
    b.record(handle="naval", run_usd=4.49)
    assert b.near_cap() is False
    b.record(handle="naval", run_usd=0.05)  # 4.54 cumulative
    assert b.near_cap() is True


def test_parse_run_usage_handles_both_field_names():
    mod = _load()
    assert mod.parse_run_usage({"usageTotalUsd": 0.5}) == 0.5
    assert mod.parse_run_usage({"usageUsd": 0.3}) == 0.3
    assert mod.parse_run_usage({"unrelated": 1}) == 0.0
    assert mod.parse_run_usage(None) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_x_budget.py -v` from `backend/`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `x_budget.py`**

Write `scripts/x_budget.py`:

```python
"""Monthly Apify spend ledger with $5/mo cap warnings."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CAP_USD = 5.00
WARN_USD = 4.50


class BudgetExhausted(Exception):
    """Raised when cumulative spend for the month is at or above CAP_USD."""


class BudgetLedger:
    """Tracks cumulative Apify spend per calendar month at a JSON path."""

    def __init__(self, path: Path, month: str | None = None) -> None:
        self.path = path
        self.month = month or datetime.now(timezone.utc).strftime("%Y-%m")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def used(self) -> float:
        return float(self._load().get(self.month, {}).get("used_usd", 0.0))

    def near_cap(self) -> bool:
        return self.used() >= WARN_USD

    def record(self, *, handle: str, run_usd: float) -> None:
        data = self._load()
        bucket = data.setdefault(self.month, {"used_usd": 0.0, "runs": []})
        bucket["used_usd"] = round(bucket.get("used_usd", 0.0) + float(run_usd), 6)
        bucket["runs"].append({
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "handle": handle,
            "cost_usd": float(run_usd),
        })
        self._save(data)

    def pre_call_check(self) -> None:
        used = self.used()
        if used >= CAP_USD:
            raise BudgetExhausted(
                f"Monthly Apify cap reached: ${used:.2f}/${CAP_USD:.2f}. "
                f"Swap APIFY_API_TOKEN or wait for next month."
            )

    def announce(self) -> None:
        """Print the budget line to stdout, and a warning to stderr if near cap."""
        used = self.used()
        print(f"[budget: ${used:.2f}/${CAP_USD:.2f} used this month]")
        if used >= WARN_USD:
            print(
                "BUDGET NEAR CAP - swap APIFY_API_TOKEN in .env when convenient",
                file=sys.stderr,
            )


def parse_run_usage(run: dict | None) -> float:
    """Extract billed USD from an Apify run dict.

    Tolerates both legacy field names (`usageTotalUsd`, `usageUsd`).
    Returns 0.0 if neither is present.
    """
    if not run:
        return 0.0
    return float(run.get("usageTotalUsd") or run.get("usageUsd") or 0.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_x_budget.py -v` from `backend/`
Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/x_budget.py backend/tests/test_x_budget.py
git commit -m "feat(x): monthly Apify budget ledger with \$4.50 warn / \$5 cap"
```

---

### Task 5: Generalized ingest core

**Files:**
- Create: `scripts/x_ingest.py`
- Test: `backend/tests/test_x_ingest.py`

This task creates a new handle-agnostic ingest module by copying the
reusable infrastructure from `scripts/naval_x_ingest.py` and parameterizing
it on `HandleConfig`. The old `naval_x_ingest.py` stays in place until
Task 9 (deletion).

- [ ] **Step 1: Write the failing tests**

Write `backend/tests/test_x_ingest.py`:

```python
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
        _apify_item("2002", " ".join(["a"] * 61)),  # > 60 words — rejected by aphorism, accepted by multiline_quote (< 500 chars, < 11 newlines)
    ]
    result = mod.ingest(handle=rumi, vault_root=tmp_path, items=items)
    # Both should be accepted under multiline_quote (item 2 is 61 single-chars under 500 total)
    assert result.added == 2


def test_ingest_dedupes_within_handle_by_text_hash(tmp_path):
    mod = _load()
    hc_mod = _load("handle_config")
    naval = next(h for h in hc_mod.HANDLES if h.name == "naval")

    items = [
        _apify_item("3001", "Calm beats anxious."),
        _apify_item("3002", "calm beats   anxious."),  # same text after normalize
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
        _apify_item("4002", "Specific knowledge is taught."),  # naval already has it
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
        _apify_item("5002", "Calm beats anxious."),  # same text, different dedup group
    ])
    assert result.added == 1  # rumi gets to keep it


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_x_ingest.py -v` from `backend/`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Read `scripts/naval_x_ingest.py`** to identify code to lift

Open `scripts/naval_x_ingest.py`. The functions to copy verbatim into `x_ingest.py`:

- `Tweet` dataclass
- `snowflake_datetime`
- `status_id_from_url`
- `clean_text`
- `slugify`
- `yaml_quote`
- `wiki_link`
- `TOPIC_RULES`

Other functions need parameterization on handle (described in Step 4 below). The constant `HANDLE = "naval"` is removed; pass the handle name everywhere it was used.

- [ ] **Step 4: Implement `scripts/x_ingest.py`**

Write `scripts/x_ingest.py`. This is the largest file in the plan. Structure:

```python
"""Handle-agnostic X ingest core.

Persists Apify items into Vault/Library/X/<handle>/ with per-handle filter
profile and within/cross-handle text-hash dedup.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from textwrap import shorten
from typing import Any


X_EPOCH_MS = 1288834974657

TOPIC_RULES: dict[str, tuple[str, ...]] = {
    "ai-and-software": ("ai", "agent", "coding", "computer", "model", "software", "vibe"),
    "business-and-startups": ("business", "capital", "career", "company", "founder", "market", "product", "startup"),
    "mind-and-attention": ("attention", "belief", "brain", "desire", "ego", "mind", "peace", "think"),
    "wealth-and-incentives": ("bitcoin", "cost", "crypto", "incentive", "money", "price", "wealth"),
    "taste-and-creativity": ("art", "create", "creativity", "design", "taste", "write"),
}


@dataclass(frozen=True)
class Tweet:
    status_id: str
    posted_utc: str
    text: str
    x_url: str
    mirror_url: str
    source: str

    @property
    def text_hash(self) -> str:
        # Match x_dedup.text_hash normalization exactly.
        normalized = " ".join(self.text.lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    @property
    def topics(self) -> list[str]:
        lowered = self.text.lower()
        matches = [
            topic for topic, keywords in TOPIC_RULES.items()
            if any(re.search(rf"\b{re.escape(k)}\b", lowered) for k in keywords)
        ]
        return matches or ["general"]


@dataclass
class IngestResult:
    fetched: int
    filtered: int
    added: int
    total: int


# --------------------------------------------------------------------------
# Sibling-module loader (project convention: scripts/ is not a package)
# --------------------------------------------------------------------------

def _load_sibling(name: str):
    path = Path(__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# Helpers (lifted verbatim from naval_x_ingest)
# --------------------------------------------------------------------------

def snowflake_datetime(status_id: str) -> datetime:
    timestamp_ms = (int(status_id) >> 22) + X_EPOCH_MS
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc)


def status_id_from_url(url: str) -> str | None:
    match = re.search(r"/status/(\d+)", url or "")
    return match.group(1) if match else None


def clean_text(text: str | None) -> str:
    text = (text or "").strip()
    text = re.sub(r"\r\n?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def slugify(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())[:8]
    return "-".join(words) or "tweet"


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def wiki_link(note_path: str, label: str) -> str:
    return f"[[{note_path}|{label}]]"


# --------------------------------------------------------------------------
# Apify mapper
# --------------------------------------------------------------------------

def tweet_from_apify_item(item: dict, *, handle_name: str, source_label: str = "Apify apidojo/tweet-scraper") -> Tweet | None:
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

    x_url = item.get("url") or item.get("tweetUrl") or f"https://x.com/{handle_name}/status/{status_id}"

    return Tweet(
        status_id=status_id,
        posted_utc=posted_utc,
        text=text,
        x_url=x_url,
        mirror_url=x_url,
        source=source_label,
    )


# --------------------------------------------------------------------------
# Path helpers
# --------------------------------------------------------------------------

def canonical_note_path(base: Path, tweet: Tweet) -> Path:
    posted = datetime.fromisoformat(tweet.posted_utc)
    filename = f"{posted:%Y-%m-%d}-{tweet.status_id}-{slugify(tweet.text)}.md"
    return base / "tweets" / f"{posted:%Y}" / filename


def relative_note_path(base: Path, tweet: Tweet, vault_root: Path) -> str:
    """Return note_path string relative to vault_root, posix-style."""
    return canonical_note_path(base, tweet).relative_to(vault_root).as_posix()


# --------------------------------------------------------------------------
# Manifest IO
# --------------------------------------------------------------------------

def read_existing_manifest(base: Path) -> dict[str, dict]:
    """Read tweets.json into {status_id: record}. Returns empty on missing/bad."""
    manifest = base / "tweets.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            return {str(item["status_id"]): item for item in data if item.get("status_id")}
        except json.JSONDecodeError:
            return {}
    return {}


def tweet_from_record(record: dict, *, source_label: str) -> Tweet | None:
    try:
        return Tweet(
            status_id=str(record["status_id"]),
            posted_utc=str(record["posted_utc"]),
            text=str(record["text"]).strip(),
            x_url=str(record.get("x_url") or ""),
            mirror_url=str(record.get("mirror_url") or ""),
            source=str(record.get("source") or source_label),
        )
    except KeyError:
        return None


# --------------------------------------------------------------------------
# Note + index writers (handle name passed in everywhere; no `naval` constants)
# --------------------------------------------------------------------------

def note_markdown(tweet: Tweet, captured_utc: str, handle_name: str) -> str:
    posted = datetime.fromisoformat(tweet.posted_utc)
    title = shorten(tweet.text.replace("\n", " "), width=80, placeholder="...")
    topics_yaml = "\n".join(f"  - {t}" for t in tweet.topics)
    tags_yaml = "\n".join([
        "  - x",
        f"  - {handle_name}",
        "  - tweet",
        *[f"  - topic/{t}" for t in tweet.topics],
    ])
    return f"""---
type: x_tweet
author: {handle_name}
handle: {handle_name}
status_id: {yaml_quote(tweet.status_id)}
posted_utc: {yaml_quote(tweet.posted_utc)}
captured_utc: {yaml_quote(captured_utc)}
source: {yaml_quote(tweet.source)}
x_url: {yaml_quote(tweet.x_url)}
mirror_url: {yaml_quote(tweet.mirror_url)}
text_hash: {yaml_quote(tweet.text_hash)}
topics:
{topics_yaml}
tags:
{tags_yaml}
---

# {posted:%Y-%m-%d} - {title}

## Tweet

{tweet.text}

## Retrieval

- Status ID: {tweet.status_id}
- Topics: {", ".join(tweet.topics)}
- X: {tweet.x_url}
"""


def write_tweet_note(base: Path, tweet: Tweet, captured_utc: str, handle_name: str) -> Path:
    path = canonical_note_path(base, tweet)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note_markdown(tweet, captured_utc, handle_name), encoding="utf-8", newline="\n")
    return path


def record_for(tweet: Tweet, base: Path, vault_root: Path) -> dict:
    return {
        "status_id": tweet.status_id,
        "posted_utc": tweet.posted_utc,
        "text": tweet.text,
        "text_hash": tweet.text_hash,
        "topics": tweet.topics,
        "x_url": tweet.x_url,
        "mirror_url": tweet.mirror_url,
        "source": tweet.source,
        "note_path": relative_note_path(base, tweet, vault_root),
    }


def write_manifests(base: Path, records: list[dict]) -> None:
    (base / "tweets.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with (base / "tweets.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_latest(base: Path, records: list[dict], captured_utc: str, handle_name: str, limit: int = 50) -> None:
    lines = [
        "---",
        "type: x_latest",
        f"author: {handle_name}",
        f"handle: {handle_name}",
        f"captured_utc: {yaml_quote(captured_utc)}",
        f"tweet_count: {min(limit, len(records))}",
        "tags:",
        "  - x",
        f"  - {handle_name}",
        "  - latest",
        "---",
        "",
        f"# @{handle_name} - Latest {min(limit, len(records))} Tweets",
        "",
    ]
    for index, record in enumerate(records[:limit], 1):
        posted = datetime.fromisoformat(record["posted_utc"])
        title = shorten(record["text"].replace("\n", " "), width=92, placeholder="...")
        note_link = wiki_link(record["note_path"], title or record["status_id"])
        lines.extend([
            f"## {index:02d}. {posted:%Y-%m-%d}",
            "",
            record["text"],
            "",
            f"- Note: {note_link}",
            f"- X: {record['x_url']}",
            "",
        ])
    (base / "latest-50.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_topic_indexes(base: Path, records: list[dict], handle_name: str) -> None:
    topics_dir = base / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    by_topic: dict[str, list[dict]] = {}
    for record in records:
        for t in record.get("topics", ["general"]):
            by_topic.setdefault(t, []).append(record)
    for topic, topic_records in sorted(by_topic.items()):
        lines = [
            "---",
            "type: x_topic_index",
            f"author: {handle_name}",
            f"topic: {topic}",
            f"tweet_count: {len(topic_records)}",
            "tags:",
            "  - x",
            f"  - {handle_name}",
            f"  - topic/{topic}",
            "---",
            "",
            f"# @{handle_name} - {topic.replace('-', ' ').title()}",
            "",
        ]
        for record in topic_records:
            posted = datetime.fromisoformat(record["posted_utc"])
            label = shorten(record["text"].replace("\n", " "), width=96, placeholder="...")
            lines.append(f"- {posted:%Y-%m-%d}: {wiki_link(record['note_path'], label)}")
        (topics_dir / f"{topic}.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_year_indexes(base: Path, records: list[dict], handle_name: str) -> None:
    years_dir = base / "years"
    years_dir.mkdir(parents=True, exist_ok=True)
    by_year: dict[str, list[dict]] = {}
    for record in records:
        year = datetime.fromisoformat(record["posted_utc"]).strftime("%Y")
        by_year.setdefault(year, []).append(record)
    for year, year_records in sorted(by_year.items(), reverse=True):
        lines = [
            "---",
            "type: x_year_index",
            f"author: {handle_name}",
            f"year: {year}",
            f"tweet_count: {len(year_records)}",
            "tags:",
            "  - x",
            f"  - {handle_name}",
            f"  - year/{year}",
            "---",
            "",
            f"# @{handle_name} - {year}",
            "",
        ]
        for record in year_records:
            posted = datetime.fromisoformat(record["posted_utc"])
            label = shorten(record["text"].replace("\n", " "), width=96, placeholder="...")
            lines.append(f"- {posted:%Y-%m-%d}: {wiki_link(record['note_path'], label)}")
        (years_dir / f"{year}.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_agent_guide(base: Path, records: list[dict], handle_name: str) -> None:
    topic_counts: dict[str, int] = {}
    for record in records:
        for t in record.get("topics", ["general"]):
            topic_counts[t] = topic_counts.get(t, 0) + 1
    topic_lines = [f"- [[Library/X/{handle_name}/topics/{t}|{t}]]: {c}" for t, c in sorted(topic_counts.items())]
    lines = [
        "---",
        "type: x_agent_guide",
        f"author: {handle_name}",
        f"tweet_count: {len(records)}",
        "tags:",
        "  - x",
        f"  - {handle_name}",
        "  - agent-memory",
        "---",
        "",
        f"# @{handle_name} Agent Guide",
        "",
        "## Retrieval Contract",
        "",
        "- Use `tweets.jsonl` for precise lookup by `status_id`, topic, date, or text search.",
        "- Use `latest-50.md` when freshness matters.",
        "- Use `topics/` when the user asks for patterns, tone, beliefs, or examples by theme.",
        "",
        "## Topic Map",
        "",
        *topic_lines,
        "",
    ]
    (base / "agent-guide.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_root_index(base: Path, records: list[dict], captured_utc: str, handle_name: str) -> None:
    years = sorted({datetime.fromisoformat(r["posted_utc"]).strftime("%Y") for r in records}, reverse=True)
    topics = sorted({t for r in records for t in r.get("topics", ["general"])})
    lines = [
        "---",
        "type: x_collection",
        f"author: {handle_name}",
        f"handle: {handle_name}",
        f"captured_utc: {yaml_quote(captured_utc)}",
        f"tweet_count: {len(records)}",
        "tags:",
        "  - x",
        f"  - {handle_name}",
        "---",
        "",
        f"# @{handle_name} X Archive",
        "",
        "## Start Here",
        "",
        f"- [[Library/X/{handle_name}/latest-50|Latest 50]]",
        f"- [[Library/X/{handle_name}/agent-guide|Agent Guide]]",
        "- `tweets.jsonl` for structured retrieval",
        "",
        "## Topic Indexes",
        "",
        *[f"- [[Library/X/{handle_name}/topics/{t}|{t}]]" for t in topics],
        "",
        "## Year Indexes",
        "",
        *[f"- [[Library/X/{handle_name}/years/{y}|{y}]]" for y in years],
        "",
        "## Sources",
        "",
        f"- https://x.com/{handle_name}",
        "",
    ]
    (base / "_index.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_state(base: Path, fetched_count: int, added_count: int, total_count: int, handle_name: str) -> None:
    state_dir = base / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "last_run_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "handle": handle_name,
        "fetched_count": fetched_count,
        "added_count": added_count,
        "total_count": total_count,
    }
    # Filename matches the old naval pattern for back-compat with existing readers.
    (state_dir / "naval_x_scraper_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


# --------------------------------------------------------------------------
# Public ingest function
# --------------------------------------------------------------------------

def ingest(*, handle, vault_root: Path, items: list[dict]) -> IngestResult:
    """Filter, dedup, persist. `handle` is a HandleConfig instance."""
    fp = _load_sibling("filter_profiles")
    dedup = _load_sibling("x_dedup")
    hc = _load_sibling("handle_config")

    base = hc.vault_base_for(handle, vault_root)
    base.mkdir(parents=True, exist_ok=True)

    # Load existing tweets (status_id-indexed) for this handle.
    existing_records = read_existing_manifest(base)
    tweets_by_id: dict[str, Tweet] = {}
    for status_id, record in existing_records.items():
        t = tweet_from_record(record, source_label=handle.source_label)
        if t:
            tweets_by_id[status_id] = t

    within_hashes = {t.text_hash for t in tweets_by_id.values()}
    sibling_handles = hc.handles_in_dedup_group(handle.dedup_group)
    cross_hashes = dedup.collect_group_text_hashes(
        handles=sibling_handles, vault_root=vault_root, exclude_name=handle.name
    )
    forbidden = within_hashes | cross_hashes

    fetched = len(items)
    filtered = 0
    added = 0
    for item in items:
        if not fp.accepts(handle.filter_profile, item):
            filtered += 1
            continue
        tweet = tweet_from_apify_item(item, handle_name=handle.name, source_label=handle.source_label)
        if not tweet:
            filtered += 1
            continue
        if tweet.text_hash in forbidden:
            continue
        if tweet.status_id in tweets_by_id:
            continue
        tweets_by_id[tweet.status_id] = tweet
        forbidden.add(tweet.text_hash)
        added += 1

    tweets = sorted(tweets_by_id.values(), key=lambda t: t.posted_utc, reverse=True)
    captured_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for tweet in tweets:
        write_tweet_note(base, tweet, captured_utc, handle.name)

    records = [record_for(tweet, base, vault_root) for tweet in tweets]
    write_manifests(base, records)
    write_latest(base, records, captured_utc, handle.name)
    write_topic_indexes(base, records, handle.name)
    write_year_indexes(base, records, handle.name)
    write_agent_guide(base, records, handle.name)
    write_root_index(base, records, captured_utc, handle.name)
    write_state(base, fetched_count=fetched, added_count=added, total_count=len(records), handle_name=handle.name)

    return IngestResult(fetched=fetched, filtered=filtered, added=added, total=len(records))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_x_ingest.py -v` from `backend/`
Expected: 6 tests PASS.

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `pytest tests/test_filter_profiles.py tests/test_handle_config.py tests/test_x_dedup.py tests/test_x_budget.py tests/test_x_ingest.py tests/test_apify_tweet_client.py -v` from `backend/`
Expected: all green. (Note: existing tests `test_aphorism_filter.py` and `test_naval_x_ingest.py` may still pass; that's fine — they get deleted in Task 9.)

- [ ] **Step 7: Commit**

```bash
git add scripts/x_ingest.py backend/tests/test_x_ingest.py
git commit -m "feat(x): handle-agnostic ingest core with profile + dedup wiring"
```

---

### Task 6: One-shot naval manifest rename

**Files:**
- Create: `scripts/migrate_naval_filenames.py`

The existing naval vault has `naval-tweets.json` and `naval-tweets.jsonl`. The new code reads `tweets.json` / `tweets.jsonl`. This task adds a one-shot rename so the next polling run sees the manifest.

- [ ] **Step 1: Write the script**

Write `scripts/migrate_naval_filenames.py`:

```python
#!/usr/bin/env python3
"""One-shot: rename naval manifest files to the handle-agnostic names.

Vault/Library/X/naval/naval-tweets.json   -> tweets.json
Vault/Library/X/naval/naval-tweets.jsonl  -> tweets.jsonl

Idempotent: if the new name already exists, leaves things alone.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


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


def run(project_root: Path) -> int:
    vault = vault_path(project_root)
    base = vault / "Library" / "X" / "naval"
    if not base.exists():
        print(f"Naval folder not found at {base}; nothing to rename.")
        return 0

    pairs = [
        ("naval-tweets.json",  "tweets.json"),
        ("naval-tweets.jsonl", "tweets.jsonl"),
    ]
    renamed_any = False
    for old_name, new_name in pairs:
        old = base / old_name
        new = base / new_name
        if not old.exists():
            print(f"skip: {old_name} does not exist")
            continue
        if new.exists():
            print(f"skip: {new_name} already exists; leaving {old_name} in place")
            continue
        old.rename(new)
        print(f"renamed: {old_name} -> {new_name}")
        renamed_any = True
    if not renamed_any:
        print("Nothing to do.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    try:
        return run(args.project_root.resolve())
    except Exception as exc:
        print(f"naval rename failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify the script syntax**

Run:
```bash
cd "c:/Users/User/OneDrive/Desktop/Vellum/Vellum"
.venv/Scripts/python.exe scripts/migrate_naval_filenames.py --help
```
Expected: usage text printed, exit 0.

- [ ] **Step 3: Run the rename**

Run:
```bash
.venv/Scripts/python.exe scripts/migrate_naval_filenames.py
```
Expected: two `renamed: ... -> ...` lines printed, exit 0. Confirm the new files exist:
```bash
ls "Vault/Library/X/naval/tweets.json" "Vault/Library/X/naval/tweets.jsonl"
```
Both should exist.

- [ ] **Step 4: Commit**

```bash
git add scripts/migrate_naval_filenames.py
git commit -m "feat(x): one-shot rename naval-tweets.{json,jsonl} -> tweets.{json,jsonl}"
```

---

### Task 7: Polling driver

**Files:**
- Create: `scripts/poll_x.py`

- [ ] **Step 1: Write the polling driver**

Write `scripts/poll_x.py`:

```python
#!/usr/bin/env python3
"""Poll Apify for configured X handles and ingest into the vault.

Iterates HANDLES from handle_config, polling each in sequence.
Fast-aborts if monthly budget is reached.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_WINDOW_HOURS = 8       # 6h cadence + 2h cushion
DEFAULT_MAX_ITEMS = 100
BUDGET_LEDGER_PATH_REL = Path("data") / "apify-budget.json"


def _load(name: str):
    path = Path(__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
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


def read_state(base: Path) -> dict:
    state_file = base / ".state" / "naval_x_scraper_state.json"
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def compute_window(state: dict, window_hours: int, now: datetime) -> tuple[datetime, datetime]:
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
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        print("APIFY_API_TOKEN missing from environment", file=sys.stderr)
        return 3

    vault = vault_path(project_root)
    client = _load("apify_tweet_client")
    ingest_mod = _load("x_ingest")
    hc = _load("handle_config")
    budget_mod = _load("x_budget")

    ledger = budget_mod.BudgetLedger(project_root / BUDGET_LEDGER_PATH_REL)

    overall_added = 0
    overall_filtered = 0
    overall_fetched = 0
    failed_handles: list[str] = []

    for handle in hc.HANDLES:
        try:
            ledger.pre_call_check()
        except budget_mod.BudgetExhausted as exc:
            print(f"BUDGET CAP REACHED before {handle.name}: {exc}", file=sys.stderr)
            ledger.announce()
            return 5

        base = hc.vault_base_for(handle, vault)
        base.mkdir(parents=True, exist_ok=True)
        state = read_state(base)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        start, end = compute_window(state, window_hours, now)

        if dry_run:
            print(json.dumps({
                "handle": handle.name,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
            }, indent=2))
            continue

        try:
            run_result = client.fetch_tweets(
                handle=handle.name,
                start=start,
                end=end,
                max_items=max_items,
                token=token,
            )
        except Exception as exc:
            print(f"[{handle.name}] Apify fetch failed: {exc}", file=sys.stderr)
            failed_handles.append(handle.name)
            continue

        # apify_tweet_client returns items directly; the run dict isn't surfaced.
        # Estimate cost from items count (cheap approximation): $0.0004/item is the
        # apidojo actor's typical rate. Real billed amount may differ; we use this
        # as an upper bound for budget tracking purposes.
        estimated_cost = round(0.0004 * len(run_result), 6)
        ledger.record(handle=handle.name, run_usd=estimated_cost)

        result = ingest_mod.ingest(handle=handle, vault_root=vault, items=run_result)
        overall_fetched += result.fetched
        overall_filtered += result.filtered
        overall_added += result.added
        print(
            f"[{handle.name}] fetched {result.fetched}, "
            f"filtered {result.filtered}, added {result.added}, total {result.total}"
        )

    ledger.announce()

    print(
        f"\nDone. fetched={overall_fetched}, filtered={overall_filtered}, "
        f"added={overall_added}, failed={failed_handles or 'none'}"
    )
    return 0 if not failed_handles else 2


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
        print(f"poll_x failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Syntax + help check**

Run:
```bash
cd "c:/Users/User/OneDrive/Desktop/Vellum/Vellum"
.venv/Scripts/python.exe scripts/poll_x.py --help
```
Expected: usage text, exit 0.

- [ ] **Step 3: Dry-run smoke test**

Run:
```bash
.venv/Scripts/python.exe scripts/poll_x.py --dry-run
```
Expected: 4 JSON blocks (one per handle) printed, exit 0. No Apify calls actually made. Budget ledger NOT touched in dry-run.

- [ ] **Step 4: Commit**

```bash
git add scripts/poll_x.py
git commit -m "feat(x): poll_x driver iterating all configured handles"
```

---

### Task 8: One-shot multi-handle backfill

**Files:**
- Create: `scripts/backfill_x.py`

- [ ] **Step 1: Write the backfill script**

Write `scripts/backfill_x.py`:

```python
#!/usr/bin/env python3
"""One-shot: backfill X aphorisms across configured handles."""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


BACKFILL_MONTHS = 12
MAX_ITEMS_PER_WINDOW = 1000
INTER_REQUEST_SLEEP_SECS = 2
BUDGET_LEDGER_PATH_REL = Path("data") / "apify-budget.json"


def _load(name: str):
    path = Path(__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
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
    windows = []
    end = now
    for _ in range(months):
        start = end - timedelta(days=30)
        windows.append((start, end))
        end = start
    return list(reversed(windows))


def run(project_root: Path, only_handle: str | None, months: int, max_per_window: int) -> int:
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        print("APIFY_API_TOKEN missing from environment", file=sys.stderr)
        return 3

    vault = vault_path(project_root)
    client = _load("apify_tweet_client")
    ingest_mod = _load("x_ingest")
    hc = _load("handle_config")
    budget_mod = _load("x_budget")
    ledger = budget_mod.BudgetLedger(project_root / BUDGET_LEDGER_PATH_REL)

    handles = hc.HANDLES if only_handle is None else [hc.get_handle(only_handle)]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    windows = month_windows(now, months)

    for handle in handles:
        print(f"\n=== {handle.name} ===")
        for start, end in windows:
            try:
                ledger.pre_call_check()
            except budget_mod.BudgetExhausted as exc:
                print(f"BUDGET CAP REACHED: {exc}", file=sys.stderr)
                ledger.announce()
                return 5
            try:
                items = client.fetch_tweets(
                    handle=handle.name,
                    start=start,
                    end=end,
                    max_items=max_per_window,
                    token=token,
                )
            except Exception as exc:
                print(f"[{handle.name}] {start.date()}..{end.date()} failed: {exc}", file=sys.stderr)
                continue
            estimated_cost = round(0.0004 * len(items), 6)
            ledger.record(handle=handle.name, run_usd=estimated_cost)
            result = ingest_mod.ingest(handle=handle, vault_root=vault, items=items)
            print(
                f"[{handle.name}] {start.date()}..{end.date()}: "
                f"fetched {result.fetched}, filtered {result.filtered}, added {result.added}"
            )
            time.sleep(INTER_REQUEST_SLEEP_SECS)

    ledger.announce()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="Backfill all configured handles")
    g.add_argument("--handle", type=str, help="Single handle name")
    parser.add_argument("--months", type=int, default=BACKFILL_MONTHS)
    parser.add_argument("--max-per-window", type=int, default=MAX_ITEMS_PER_WINDOW)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()

    if not args.all and not args.handle:
        # default to --all
        only = None
    else:
        only = args.handle if args.handle else None

    try:
        return run(args.project_root.resolve(), only, args.months, args.max_per_window)
    except Exception as exc:
        print(f"backfill_x failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Syntax + help check**

Run:
```bash
cd "c:/Users/User/OneDrive/Desktop/Vellum/Vellum"
.venv/Scripts/python.exe scripts/backfill_x.py --help
```
Expected: usage text, exit 0.

**DO NOT run the live backfill in this task.** The user runs it manually (with a fresh `APIFY_API_TOKEN`) after the full plan completes.

- [ ] **Step 3: Commit**

```bash
git add scripts/backfill_x.py
git commit -m "feat(x): one-shot multi-handle backfill (--all or --handle)"
```

---

### Task 9: Delete superseded naval-specific scripts and tests

**Files:**
- Delete: `scripts/aphorism_filter.py`
- Delete: `scripts/naval_x_ingest.py`
- Delete: `scripts/scrape_naval_x.py`
- Delete: `scripts/backfill_naval_x.py`
- Delete: `scripts/run_naval_x_scrape.ps1`
- Delete: `backend/tests/test_aphorism_filter.py`
- Delete: `backend/tests/test_naval_x_ingest.py`

- [ ] **Step 1: Verify nothing else imports the deleted modules**

Run from project root:
```bash
cd "c:/Users/User/OneDrive/Desktop/Vellum/Vellum"
grep -rn "aphorism_filter\|naval_x_ingest\|scrape_naval_x\|backfill_naval_x" backend/ scripts/ --include="*.py" 2>&1
```
Expected: zero hits. (All references should already be replaced by the new modules from Tasks 1-8.)

If any file shows a hit, STOP and investigate before deleting. The remaining references must be replaced first.

- [ ] **Step 2: Delete the files**

```bash
git rm scripts/aphorism_filter.py
git rm scripts/naval_x_ingest.py
git rm scripts/scrape_naval_x.py
git rm scripts/backfill_naval_x.py
git rm scripts/run_naval_x_scrape.ps1
git rm backend/tests/test_aphorism_filter.py
git rm backend/tests/test_naval_x_ingest.py
```

- [ ] **Step 3: Run the full naval-related test suite to confirm green**

```bash
cd backend
c:/Users/User/OneDrive/Desktop/Vellum/Vellum/.venv/Scripts/python.exe -m pytest tests/test_filter_profiles.py tests/test_handle_config.py tests/test_x_dedup.py tests/test_x_budget.py tests/test_x_ingest.py tests/test_apify_tweet_client.py -v
```
Expected: every test in those five files passes (~55 tests total).

- [ ] **Step 4: Commit**

```bash
cd "c:/Users/User/OneDrive/Desktop/Vellum/Vellum"
git commit -m "chore(x): remove superseded naval-specific scripts and tests"
```

---

### Task 10: Update CLAUDE.md folder-policy exception clause

**Files:**
- Modify: `Vellum/CLAUDE.md` (around line 531)

- [ ] **Step 1: Edit CLAUDE.md**

In `c:/Users/User/OneDrive/Desktop/Vellum/Vellum/CLAUDE.md`, find the line that starts with:

```
Exception: explicit ingestion and retention automation may manage public source folders (`X/`, `Youtube/`, and `Sports/`)
```

Replace it with:

```
Exception: explicit ingestion and retention automation may manage public source folders (`Library/X/`, `Library/Youtube/`, and `Library/Sports/`)
```

(Only the three folder paths change; rest of the sentence stays.)

- [ ] **Step 2: Commit**

```bash
cd "c:/Users/User/OneDrive/Desktop/Vellum/Vellum"
git add CLAUDE.md
git commit -m "docs(claude): folder-policy exception names Library/-prefixed paths"
```

---

### Task 11: Switch the Windows scheduled task to multi-handle poller @ 6h

**Files:**
- Create: `scripts/run_x_poll.ps1`

Operational (no commit needed for the schtasks commands themselves; the PS1 file is committed below):

- [ ] **Step 1: Create the new PowerShell wrapper**

Write `scripts/run_x_poll.ps1`:

```powershell
$ErrorActionPreference = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectRoot "data\logs"
$Driver = Join-Path $ScriptDir "poll_x.py"
$LogFile = Join-Path $LogDir "x-poll.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $ProjectRoot

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
"[$timestamp] Starting X poll" | Out-File -FilePath $LogFile -Append -Encoding utf8

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    & $VenvPython $Driver *>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8
} else {
    & python $Driver *>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8
}

$exitCode = $LASTEXITCODE
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
"[$timestamp] Finished X poll with exit code $exitCode" | Out-File -FilePath $LogFile -Append -Encoding utf8

exit $exitCode
```

- [ ] **Step 2: Commit the PS1**

```bash
cd "c:/Users/User/OneDrive/Desktop/Vellum/Vellum"
git add scripts/run_x_poll.ps1
git commit -m "feat(x): PowerShell wrapper for the multi-handle X poller"
```

- [ ] **Step 3: Unregister the old NavalXPoller task**

In PowerShell:

```powershell
Get-ScheduledTask -TaskName "NavalXPoller" -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
Write-Output "NavalXPoller removed (if it existed)."
```

- [ ] **Step 4: Register the new XPoller task @ every 6h**

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"C:\Users\User\OneDrive\Desktop\Vellum\Vellum\scripts\run_x_poll.ps1`"" `
    -WorkingDirectory "C:\Users\User\OneDrive\Desktop\Vellum\Vellum"

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Hours 6)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -MultipleInstances IgnoreNew

# Register the task DISABLED — the user wants explicit enable when budget allows.
Register-ScheduledTask -TaskName "XPoller" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "Polls Apify every 6h for all configured X handles" `
    -User "$env:USERNAME" -RunLevel Limited | Out-Null

Disable-ScheduledTask -TaskName "XPoller" | Out-Null

Get-ScheduledTask -TaskName "XPoller" | Select-Object TaskName, State | Format-Table -AutoSize
```

Expected: `TaskName: XPoller, State: Disabled`. The user enables it manually with `Enable-ScheduledTask -TaskName "XPoller"` once they're ready (fresh Apify token + backfill done).

- [ ] **Step 5: Confirm task definition is correct**

```powershell
$t = Get-ScheduledTask -TaskName "XPoller"
$t.Triggers | Format-List
$t.Actions | Format-List
```

Expected: trigger has `DaysInterval` blank and `Repetition.Interval = PT6H` (or similar). Action points to `run_x_poll.ps1`.

---

## Self-Review

**Spec coverage:**
- Handle config registry: Task 2 ✓
- Three filter profiles: Task 1 ✓
- Text-hash dedup (within + cross): Tasks 3 + 5 ✓
- Apify budget ledger ($4.50 warn / $5.00 cap): Task 4 + integrated in Tasks 7, 8 ✓
- Handle-agnostic ingest core: Task 5 ✓
- Polling driver: Task 7 ✓
- One-shot backfill: Task 8 ✓
- PowerShell wrapper + schtasks: Task 11 ✓
- Naval data migration (`naval-tweets.json` → `tweets.json`): Task 6 ✓
- Delete old naval-specific code: Task 9 ✓
- CLAUDE.md folder-policy update: Task 10 ✓
- Vault path `Vault/Library/X/<handle>/` everywhere: Tasks 2, 5, 6, 7, 8 ✓

**Placeholder scan:** No `TBD`, `TODO`, "similar to Task N", or "implement later" references. All steps contain executable code or commands.

**Type consistency:**
- `IngestResult` fields (`fetched, filtered, added, total`) used identically across Tasks 5, 7, 8.
- `BudgetLedger` API (`record`, `pre_call_check`, `announce`, `near_cap`, `used`) used identically in Tasks 4, 7, 8.
- `HandleConfig` fields (`name, filter_profile, dedup_group, source_label`) consistent across Tasks 2, 5, 7, 8.
- `vault_base_for(handle, vault)` signature consistent in Tasks 2 and 5.

**Cost-estimate note for executor:** the polling/backfill drivers estimate Apify cost as `$0.0004 × len(items)` after each run. This is a rough upper bound for the apidojo actor. If the actor's `run.get("usageTotalUsd")` becomes accessible through a different SDK path later, swap the estimation for the real billed amount via `budget_mod.parse_run_usage(run)`.

**Notes for the executor:**
- Run all `pytest` commands from `c:/Users/User/OneDrive/Desktop/Vellum/Vellum/backend/`.
- Per-file `git add` in every commit. Branch is `feat/multi-handle-x`. Do NOT sweep in unrelated working-tree changes.
- The `NavalXPoller` Windows task is currently disabled (from prior conversation). Task 11 deletes it and registers `XPoller` in a disabled state by default.
