---
type: design-spec
topic: naval-x-apify-scraper
created: 2026-05-16
status: draft
---

# Naval X Scraper — Migrate to Apify (Aphorism Filter, Near-Real-Time Polling)

## Problem

The daily 5am scheduled scrape at `scripts/scrape_naval_x.py` calls
`techtwitter.com`, a public nitter-style mirror. The mirror is stale-capped:
it returns the same 48 tweets every run. Logs show `added 0` for every run
since the first. New naval posts never reach the vault.

The user also wants a more event-like model: catch tweets as naval posts them,
not once a day. True push (X webhooks) requires the paid X Developer API.
The realistic substitute without an X dev account is high-frequency polling.

## Goal

Replace techtwitter with a reliable, scalable scraper that:

1. Captures naval's tweets without an X developer account or X API credits.
2. Filters to **aphorisms** only — short, standalone, complete-thought tweets
   (what people screenshot). Excludes podcast TOCs, link-only posts, threads,
   replies, retweets.
3. Runs as a **15-minute polling task** going forward (near-real-time;
   typical capture latency < 15 minutes after naval posts).
4. Has a **separate one-shot backfill** script for the last 12 months,
   run manually once.
5. Keeps the existing vault layout (`X/naval/tweets/YYYY/`, `latest-50.md`,
   topic/year indexes, `naval-tweets.jsonl`).

## Why polling, not webhooks

Real "when naval tweets" push notifications require:
- X Filtered Stream API ($100/mo paid tier) — explicitly out of scope.
- Or third-party services (IFTTT/Zapier "new tweet" trigger, Tweetshift, etc.)
  — all broken since X locked down their API in 2023.

Near-real-time polling at 15-min cadence is the production-quality substitute.
Functional behaviour: aphorism appears in the vault within ~15 minutes of
naval posting it. No tweet is ever lost — the script always asks "what's new
since the last status_id we wrote", so PC downtime just means a bigger
catch-up batch on next boot.

## Approach

### Data source: Apify `apidojo/tweet-scraper` (REST API, direct)

- `APIFY_API_TOKEN` already exists in `.env`.
- Direct REST (not MCP) because the polling task is unattended and MCP
  requires an agent driver.
- Actor inputs:
  - `twitterHandles: ["naval"]`
  - `start` / `end` (ISO date) for windowed fetch
  - `maxItems` cap
  - `sort: "Latest"`
- Costs:
  - Polling: ~96 actor runs/day, each returning 0–few items.
    Estimated total: ~$0.50–1.50/month.
  - Backfill (one-shot, last 12 mo): ~$0.60.

### Aphorism filter (post-fetch, client-side)

`scripts/aphorism_filter.py` — pure function `is_aphorism(item) -> bool`.
Rules: ALL of these must hold.

- `isRetweet == false` and `isReply == false`
- `isQuote == false` (X quote-tweets pull in context we don't want)
- `text` length ≤ 280 chars after normalization
- No URL (`https?://` regex against text)
- No `@mention` at start of text
- No media attached (`media` array empty)
- Newline count ≤ 1 (excludes podcast TOCs, multi-line lists)
- Sentence count ≤ 3 (split on `.`, `!`, `?`)
- Word count between 3 and 60

Filter logic isolated so it's tunable without touching scrape orchestration.

### Architecture — two entry points

```
scripts/
├── apify_tweet_client.py     ← thin Apify REST wrapper (new, shared)
├── aphorism_filter.py        ← classification rules (new, shared)
├── naval_x_ingest.py         ← shared ingest core (new) — apply filter,
│                                merge with manifest, write notes/indexes
├── scrape_naval_x.py         ← polling entry point (rewrite of existing)
│                                — fetches last ~30 min of tweets, ingests
├── backfill_naval_x.py       ← one-shot 12-month backfill (new)
│                                — paginates by month, ingests
└── run_naval_x_scrape.ps1    ← updated; task scheduler still calls this
```

**`apify_tweet_client.py`** — `fetch_tweets(handle, start, end, max_items,
token) -> list[dict]`. Calls
`POST https://api.apify.com/v2/acts/apidojo~tweet-scraper/run-sync-get-dataset-items?token=...`
with 120s timeout, one retry on network failure. Raises on non-2xx.

**`naval_x_ingest.py`** — `ingest(items: list[dict]) -> IngestResult` —
loads existing manifest, dedupes by `status_id`, applies `is_aphorism`,
writes per-tweet markdown notes, regenerates `latest-50.md`, topic indexes,
year indexes, `naval-tweets.json`, `naval-tweets.jsonl`. Existing functions
in the current `scrape_naval_x.py` move here.

**`scrape_naval_x.py` (polling)** — what the 15-min task calls.
1. Load `.env`, read `APIFY_API_TOKEN`.
2. Read last-run timestamp from `.state/naval_x_scraper_state.json`.
3. Compute window: `start = max(last_run, now - 2h)` (2h cushion for
   missed runs), `end = now`.
4. Fetch via `apify_tweet_client.fetch_tweets`.
5. Call `naval_x_ingest.ingest`.
6. Write new state.
7. Exit 0 if all OK; non-zero on error.

**`backfill_naval_x.py`** — manually invoked once.
1. Load `.env`, read `APIFY_API_TOKEN`.
2. Iterate month-by-month over the last 12 months.
3. For each month, fetch up to 1000 tweets, ingest, sleep 2s.
4. Print summary: months scanned, total fetched, aphorisms added.
5. Exits 0 on success.

### Scheduling — Windows Task Scheduler @ every 15 min (flavor A)

The existing scheduled task already invokes `run_naval_x_scrape.ps1`.
Change required:

- Cadence: from daily 5am to **every 15 minutes**.
- `run_naval_x_scrape.ps1` content is unchanged (still calls
  `scripts/scrape_naval_x.py`); only the trigger schedule changes.
- Implementation note: I'll provide the `schtasks /Create` command in the
  plan. User runs it once.

PC-off behaviour: missed polls catch up automatically because the script
asks Apify for `start = last_run_time` — even after a 3-day outage, the
next run captures everything.

### Migration of existing data

Non-destructive (Option 1 from previous spec stays). Old per-tweet notes
under `tweets/YYYY/` remain. `latest-50.md` and topic/year indexes
auto-clean on next run because they regenerate from the manifest. Any
non-aphorism notes (e.g., podcast TOCs) stay on disk but disappear from
the surface indexes — acceptable since they're per-tweet canonical memory.

### CLAUDE.md update

Section 3 currently restricts Apify to "Amazon product scraper only".
Broaden to include the tweet-scraper actor:

> **Apify (REST API for scheduled ingestion + MCP for agent calls)**
> - REST API used by scheduled scrapers (Amazon, X tweet archive) with
>   `APIFY_API_TOKEN`.
> - MCP (`https://mcp.apify.com/sse`) used for agent-driven scraping
>   (Amazon product lookups).
> - Output is ALWAYS stored locally first, THEN scrubbed if YELLOW, THEN
>   summarized before the LLM sees any of it.
> - Never used as a general web scraper without explicit user instruction.

`X/` is already INDEXED, SENT, TOOL ACCESSIBLE per the folder policy.

### Testing

- Unit tests for `aphorism_filter.is_aphorism` covering:
  - reply, retweet, quote → reject
  - tweet with URL → reject
  - podcast TOC (multi-newline) → reject
  - single-line ≤ 280 char wisdom → accept
  - 60-word boundary on either side
- Unit tests for `naval_x_ingest` covering dedupe-by-status_id and
  manifest merge.
- Integration test with mocked Apify response (20 mixed items) asserting
  correct subset survives.
- Manual smoke: `python scripts/scrape_naval_x.py --dry-run` against
  live Apify, confirm a sane number of items returned and one true
  aphorism makes it through the filter.

### Failure modes

| Failure | Behavior |
|---|---|
| Apify API timeout | One retry, then exit 2, log, no vault changes. |
| Apify returns empty list | Log info ("no new tweets"), exit 0. |
| `APIFY_API_TOKEN` missing | Exit 3, explicit message; no fallback. |
| Actor input rejected (4xx) | Exit 4, response body in log. |
| Manifest write fails mid-run | Existing notes intact; next run retries. |

PowerShell scheduled task captures stdout/stderr to
`data/logs/naval-x-scrape.log` — unchanged.

## Out of scope

- True webhook-based push (requires paid X API).
- Other handles. Code is parameterised so a second handle is trivial later.
- Re-ingesting older aphorisms (>12 months). User can run another backfill
  window manually later if desired.
- Notification/alerting on new tweet capture (logs only).

## Decision summary

- Source: **Apify `apidojo/tweet-scraper`** via REST.
- Filter: **aphorism heuristics** (user selection B).
- Polling: **Windows Task Scheduler @ every 15 min** (user selection A).
- Backfill: **one-shot `backfill_naval_x.py`** for last 12 months, user-invoked.
- Existing vault layout preserved (non-destructive migration).
- CLAUDE.md Section 3 broadens Apify allowlist.
