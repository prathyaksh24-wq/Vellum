---
type: design-spec
topic: multi-handle-x-quotes
created: 2026-05-16
status: draft
supersedes: 2026-05-16-naval-x-apify-scraper-design.md
---

# Multi-Handle X Quotes Pipeline

## Problem

The naval-only scraper built earlier today (per
`2026-05-16-naval-x-apify-scraper-design.md`) is hardcoded to a single
handle. The user wants a deep corpus of quote-style tweets across four
voices — naval, NavalismHQ, rumilyrics, AlexHormozi — so the Vellum agent
can speak fluently to life, philosophy, and business. Each handle has a
different content shape, and several constraints make this non-trivial:

- The user stays on Apify's free tier ($5/mo per account) and rotates
  tokens when capped. The system must surface usage before the cap hits.
- Rumi's account reposts identical quotes under different status_ids.
  Status-id dedup is insufficient — text-content dedup is required.
- NavalismHQ aggregates naval quotes — cross-account dedup against naval
  is required to avoid duplicate content.
- Hormozi posts long multi-paragraph mini-essays with bullet lists. The
  current strict aphorism filter rejects ~all of his content.
- The vault was reorganized: X content now lives at `Vault/Library/X/`,
  not `Vault/X/`.

## Goal

A handle-agnostic X scraping pipeline that:

1. Polls four configured handles every 6 hours, applying per-handle filter
   profiles, with cross-account text-content dedup for naval/NavalismHQ.
2. Tracks cumulative Apify spend per month, warns at $4.50, refuses calls
   at $5.00.
3. Provides a one-shot 12-month backfill across all handles.
4. Stays drop-in compatible with the existing `Vault/Library/X/naval/`
   data layout — no destructive migration.
5. Survives token rotation without state corruption.

## Approach

### Handle config registry

A handle is a configuration row, not a hardcoded constant.

```python
@dataclass(frozen=True)
class HandleConfig:
    name: str                  # e.g. "naval", case-preserved
    filter_profile: str        # key into FILTER_PROFILES
    dedup_group: str           # cross-handle dedup scope
    source_label: str          # for tweet frontmatter

HANDLES = [
    HandleConfig(name="naval",       filter_profile="aphorism",        dedup_group="naval"),
    HandleConfig(name="NavalismHQ",  filter_profile="aphorism",        dedup_group="naval"),
    HandleConfig(name="rumilyrics",  filter_profile="multiline_quote", dedup_group="rumi"),
    HandleConfig(name="AlexHormozi", filter_profile="original_tweet",  dedup_group="hormozi"),
]
```

Each handle gets its own folder at `Vault/Library/X/<name>/` (case
preserved exactly as the X URL). Internal layout matches the current
naval folder: `tweets/YYYY/`, `topics/`, `years/`, `latest-50.md`,
`agent-guide.md`, `_index.md`, `tweets.json`, `tweets.jsonl`, `.state/`.

### Filter profiles

Three profiles, registered in `scripts/filter_profiles.py`:

**`aphorism`** (used by naval, NavalismHQ) — strict, identical to current
`is_aphorism`:
- `isRetweet`, `isReply`, `isQuote` all false
- No URL, no media, no `@`-start
- ≤1 newline, ≤3 sentences, 3–60 words, ≤280 chars

**`multiline_quote`** (used by rumilyrics) — relaxed for couplets and
short verses:
- `isRetweet`, `isReply`, `isQuote` all false
- No URL, no media, no `@`-start
- ≤10 newlines, ≤500 chars, ≥3 words
- No sentence-count limit

**`original_tweet`** (used by AlexHormozi) — minimal for mini-essays:
- `isRetweet`, `isReply`, `isQuote` all false
- No URL, no media
- ≥10 words
- No length, newline, sentence, or character limits

The shared rejection rules (retweet/reply/quote/media/URL) are factored
into a `_is_original(item)` helper so each profile only declares its
additions.

### Dedup

Two layers.

**Within-handle dedup** (always on): tweet's normalized `text_hash` is
checked against `<handle>/tweets.json`'s `text_hash` index. Match → skip.

**Cross-handle dedup** (within the same `dedup_group`): before writing
under handle X, check every other handle in the same dedup_group for the
same `text_hash`. Match → skip. Cuts NavalismHQ duplicates of naval
content automatically.

Normalization is conservative: `text_hash = sha256(text.lower().split())[:16]` —
lowercased, whitespace-collapsed, punctuation preserved. Strong enough
to catch "exact same quote, different status_id"; not aggressive enough
to conflate distinct short tweets that happen to share words.

The dedup helper lives in `scripts/x_dedup.py` so its logic is testable
in isolation.

### Budget tracking

`scripts/x_budget.py` owns the monthly spend ledger at
`data/apify-budget.json`:

```json
{
  "2026-05": {
    "used_usd": 4.97,
    "runs": [
      {"ts": "2026-05-16T11:36:00+00:00", "handle": "naval", "cost_usd": 0.012}
    ]
  }
}
```

After each Apify actor run, the wrapper reads the run's billed usage
defensively: `run.get("usageTotalUsd") or run.get("usageUsd") or 0.0`
(Apify SDK has shipped both field names historically). Append the
result to the monthly bucket. After append:

- Prints `[budget: $X.XX/$5.00 used this month]` to stdout (goes to log).
- If cumulative ≥ $4.50: also prints
  `BUDGET NEAR CAP — swap APIFY_API_TOKEN in .env when convenient` to stderr.
- If cumulative ≥ $5.00: `pre_call_check()` raises `BudgetExhausted` and
  the polling/backfill driver exits with code 5 BEFORE making any actor
  call this run. (Avoids the actor's own free-plan rejection error.)

Token rotation: when the user edits `.env` to a new `APIFY_API_TOKEN`,
the budget ledger continues accumulating into the same monthly bucket.
That's a feature — the ledger tracks "spend this calendar month" not
"spend on this account". On the 1st of next month, a new month bucket
starts at zero.

### Polling driver

`scripts/poll_x.py` is the scheduled entry point.

```
load_dotenv → check APIFY_API_TOKEN → load HANDLES from handle_config →
  for each handle:
    budget.pre_call_check()      # exit 5 if cap hit
    items = apify_tweet_client.fetch_tweets(...)
    budget.record(run_usage)
    x_ingest.ingest(handle, items)
  print totals
  exit 0
```

Each handle's polling window is independent (each handle's `.state/`
file tracks its own `last_run_utc`). One scheduled run hits all four
handles sequentially. Typical wall time: ~2 min per run (4 actor calls
× ~30s each). One-shot run can still process partial handles if budget
caps mid-run — already-processed handles are saved; the next run picks
up the rest.

### Backfill

`scripts/backfill_x.py` does the one-shot 12-month backfill. Flags:

- `--all` (default): all configured handles
- `--handle <name>`: a single handle
- `--months <n>` (default 12): backfill depth
- `--max-per-window <n>` (default 1000): per-month item cap

Behavior: for each handle × month-window, call Apify, ingest. Budget
checks between every (handle, month). If cap hits, exit cleanly with a
"resume next month or rotate token" message. State files remember which
windows were processed so the next invocation skips them.

**Critical:** the backfill must run on a fresh APIFY_API_TOKEN — current
May budget is ~$0.03 remaining, far short of the ~$3–5 backfill cost.

### Schedule

One Windows Task `XPoller`, every 6 hours, runs
`scripts/run_x_poll.ps1` which invokes `python scripts/poll_x.py`. The
old `NavalXPoller` task is unregistered as part of the migration.

The PS1 wrapper continues the lessons from the prior implementation:
- `$ErrorActionPreference = "Continue"`
- `*>&1` redirect so all streams flow into the log
- No stale `--max-tweets` flag
- Writes `Started` / `Finished` markers around the Python call

### Migration of existing naval data

Non-destructive. The current naval data already lives at
`Vault/Library/X/naval/` (the user already moved it). The renames it
needs:

- `naval-tweets.json` → `tweets.json`
- `naval-tweets.jsonl` → `tweets.jsonl`

A one-time `scripts/migrate_naval_filenames.py` does these renames. The
content of the JSON is unchanged. On next polling run, all surface files
(`latest-50.md`, `topics/`, `years/`, `agent-guide.md`, `_index.md`)
regenerate from the renamed manifest and will use the new filename.

Old naval-specific scripts get deleted in the same commit set:
`scripts/aphorism_filter.py`, `scripts/naval_x_ingest.py`,
`scripts/scrape_naval_x.py`, `scripts/backfill_naval_x.py`,
`scripts/run_naval_x_scrape.ps1`. Old tests
(`backend/tests/test_aphorism_filter.py`,
`backend/tests/test_naval_x_ingest.py`) deleted in the same commit set
and replaced by the new handle-agnostic tests.

### CLAUDE.md update

The earlier Apify allowlist edit at line 231 already broadened to cover
"X tweet archive" — no further change needed. The folder policy at line
520 already lists `Library/` (with X under it) as forbidden for agent
writes but covered by the ingestion-automation exception at line 531.
The exception clause currently names `X/`, `Youtube/`, `Sports/` as bare
paths; a one-line clarification updates it to `Library/X/`, `Library/Youtube/`,
`Library/Sports/`. Not strictly required for code to work, but keeps the
operational contract honest.

## Testing

| File | Coverage |
|---|---|
| `test_filter_profiles.py` | 3 profile classes; aphorism reuses prior 15 cases; multiline_quote adds 8 cases (couplet accepted, 10-newline boundary, 500-char boundary, etc.); original_tweet adds 6 cases (long mini-essay accepted, 9-word rejected, URL rejected, etc.) |
| `test_x_dedup.py` | within-handle: exact text dupe rejected, normalization variants rejected; cross-handle: naval already-has-it blocks NavalismHQ write; different dedup_groups don't interfere |
| `test_x_budget.py` | first run creates monthly bucket, subsequent runs append, threshold prints at $4.50, pre_call_check raises at $5.00, new month starts fresh |
| `test_x_ingest.py` | replaces test_naval_x_ingest.py; parameterized over HandleConfig; verifies handle-specific filter + dedup applied; verifies vault path is `Vault/Library/X/<name>/` |
| `test_handle_config.py` | HANDLES registry shape, no duplicate handle names, dedup groups validation |

## Failure modes

| Failure | Behavior |
|---|---|
| Apify timeout | One retry, then exit 2 for that handle. Continue with next handle. |
| Apify returns empty | Log info, exit 0 for that handle. |
| `APIFY_API_TOKEN` missing | Exit 3 before any handle is touched. |
| Apify 4xx (bad input) | Exit 4 for that handle. Continue with next handle. |
| Budget pre-check fails | Exit 5 before that handle's Apify call. Already-processed handles are saved. |
| Manifest write fails mid-handle | That handle's notes stay intact from prior run; next run retries. Other handles unaffected. |
| Cross-handle dedup file missing for sibling | Treat as empty; no cross-dedup applied; log a warning. |

The PowerShell wrapper captures stdout/stderr to
`data/logs/x-poll.log` (renamed from `naval-x-scrape.log`).

## Out of scope

- Real-time push notifications (still requires X paid API).
- Handles other than the four configured.
- Backfill depths beyond 12 months (user can re-run with `--months 24` later).
- Multi-account budget aggregation (each account = own $5/mo).
- Automated token rotation (user does it manually when they see the warning).
- Cross-handle topic indexing (each handle's topics are independent).

## File map

```
scripts/
├── handle_config.py          ← NEW: HandleConfig + HANDLES registry
├── filter_profiles.py        ← NEW: 3 filter profiles
├── apify_tweet_client.py     ← KEEP: unchanged
├── x_dedup.py                ← NEW: text-hash dedup logic
├── x_budget.py               ← NEW: monthly $5 ledger + warnings
├── x_ingest.py               ← NEW: handle-agnostic ingest core
├── poll_x.py                 ← NEW: polling driver (all handles)
├── backfill_x.py             ← NEW: one-shot backfill (all or one)
├── run_x_poll.ps1            ← NEW: PowerShell wrapper
└── migrate_naval_filenames.py ← NEW: one-shot rename of naval manifest

deletes:
- scripts/aphorism_filter.py
- scripts/naval_x_ingest.py
- scripts/scrape_naval_x.py
- scripts/backfill_naval_x.py
- scripts/run_naval_x_scrape.ps1
- backend/tests/test_aphorism_filter.py
- backend/tests/test_naval_x_ingest.py

backend/tests/
├── test_handle_config.py     ← NEW
├── test_filter_profiles.py   ← NEW (covers aphorism + 2 new profiles)
├── test_x_dedup.py           ← NEW
├── test_x_budget.py          ← NEW
└── test_x_ingest.py          ← NEW (replaces test_naval_x_ingest.py)

ops:
- Unregister Windows Task `NavalXPoller`
- Register Windows Task `XPoller` (every 6h)
- Optionally edit CLAUDE.md line 531 to use `Library/` prefix
```

## Decision summary

- **Architecture:** handle-agnostic generalization with config registry.
- **Filters:** three profiles (aphorism / multiline_quote / original_tweet).
- **Dedup:** text-hash within handle + cross-handle for same dedup_group.
- **Budget:** monthly ledger, warn at $4.50, refuse at $5.00, token rotation handled by env edit.
- **Cadence:** every 6 hours, all handles in one driver run.
- **Vault path:** `Vault/Library/X/<handle>/` with case preserved.
- **Migration:** rename `naval-tweets.json{l}` → `tweets.json{l}`, regenerate indexes; old naval scripts deleted.
