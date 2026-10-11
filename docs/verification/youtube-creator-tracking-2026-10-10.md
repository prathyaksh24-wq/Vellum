# YouTube creator tracking verification — 2026-10-10

## Implemented scope

Adaptive creator selection extends the existing YouTube plugin, Knowledge Core,
Automation scheduler, and ConversationLifecycle. Knowledge Core schema 15 adds
derived watch activity, bounded daily aggregates, a durable upload outbox, and
worker leases. No separate database, scheduler, or model-based polling loop was
introduced. Personal creator rules remain in local runtime configuration.

The owner explicitly authorized combining imported Takeout history with the
currently selected browser account. Other account history remains outside the
selected scope. The resulting profile distinguishes long-term, current,
seasonal, former, excluded, and automatically selected creators. Search queries
and recommendation exposure do not endorse creators. Seasonal monitoring follows
recent viewing evidence; it does not infer a sports calendar.

Configuration preserves explicit corrections, validates the merged 200-rule
limit before writes, and retains seed timestamps only for current rules.
Account scope, timezone, and topic-filter changes rebuild the derived counts.
Public feed polling has a shared rolling request budget across scheduled and
manual runs, including individual reservations around window boundaries.

## Initial working-checkout verification

These checks were captured before publication, in the working checkout that
also contained unrelated pending changes. The isolated PR validation below
checks the feature alone against the latest `main`.

| Check | Observed result |
| --- | --- |
| Affected backend suite: YouTube, Automations, Knowledge Core, automation App Actions | 308 passed, 2 skipped, 53.73 seconds |
| Creator-specific tests included in that suite | 27 tests passed |
| YouTube specialist routing checks | 10 passed |
| API health and capability checks | 4 passed |
| Frontend Vitest suite | 318 passed across 37 files |
| Frontend production build | Passed |
| Git whitespace check | Passed |
| Installed Knowledge Core `PRAGMA quick_check` | `ok` |

The skipped backend checks require opt-in installed-browser and Chromium DOM
fixtures. This is not a claim that those live browser checks passed. Backend
tests reported an existing Starlette/AnyIO deprecation warning; the frontend
build reported existing classic-script module warnings.

Coverage includes linked-account isolation and cross-source video/day dedup,
local timezone midnight boundaries, current-interest decay, seasonal return,
former/excluded overrides, rename-safe exclusions, legacy preference
invalidation, explicit ad and search rejection, title topic gates, quiet
baselines, title edits, restart/crash delivery retries, missing destinations,
rolling and daily request caps, provider backoff, attribution queues, lease
expiry, API fallback ownership, and HTTP/App Action contracts. A 20-year,
7,300-record fixture verifies bounded aggregates and fast unchanged reads.
Automation tests forbid chat-model calls and verify canonical run receipts and
idempotent conversation delivery. A transient Windows sharing-lock test verifies
bounded retries for the existing atomic AutomationStore writer.

## Installed data and measured performance

| Measurement | Observed result |
| --- | --- |
| Selected history observations projected | 50,888 |
| Initial full projection | 7.217 seconds |
| Initial eight-channel collection | 12.069 seconds |
| Initial snapshot read | 90.658 milliseconds |
| Final snapshot read | 119.573 milliseconds |
| Unchanged refresh | 0.253 seconds; zero new observations or network requests |
| Raw Takeout watch observations after migration | 50,773; unchanged |

During the installed collection, all eight public RSS reads encountered
intermittent failures. All eight connected Data API fallback checks succeeded
and created quiet baselines. No historical-upload notification was delivered.
Earlier live probes also observed successful public Atom responses; availability
was inconsistent. The fallback uses the existing read-only connected client and
public channel uploads metadata. No new OAuth scopes were added.

Final read-only state verification found 20 monitored creators, eight baselined
channels, 12 resolved brand exclusions, no warnings, and status `baselining`.
Former-interest overrides remain inactive. There are 18,817 video/day records
queued for ownership attribution and zero currently marked unavailable. These
are records, not necessarily distinct videos; background lookup processes up to
50 distinct public video IDs per 15 minutes. Historical ownership coverage is
therefore progressive rather than complete.

## Operating limits and acceptance boundaries

The saved **YouTube creator uploads** automation is active every 15 minutes,
delivering through Vellum's normal new-chat destination. Vellum's backend was
not listening on port 8000 at initial verification. Scheduled checks execute
when the backend is started; no operating-system service was installed.

The installed limits are 20 monitored channels, eight public feed attempts per
rolling 15 minutes, 768 feed attempts per UTC day, and 1,536 reserved API
fallback units per UTC day. Feed responses are capped at 256 KiB and 50 parsed
entries. API fallback reads the newest 15 uploads. Missing-ownership metadata
lookups have their own bounded batch schedule. These are application settings,
not guaranteed public RSS allowances. See the [implementation notes](../youtube-creator-tracking.md)
for transports, quota accounting, and privacy boundaries.

This verification does not establish years of unattended live operation, a
real future-upload notification arrival, watch duration, exact repeat plays,
complete lifetime watch totals, historical subscription dates, or continuous
personal search capture. Counts represent saved distinct video/day records.
Topic filtering uses title keywords and can miss relevant titles. Short feed
windows cannot guarantee recovery of all uploads after extended downtime.

## Publication preparation and server startup

After publication was authorized, the feature was isolated on
`codex/youtube-adaptive-creator-tracking`, based on `main` at `1ce1940`.
Only creator-tracking source, tests, and documentation are included. Unrelated
pending changes remain in the original working checkout. Private history,
creator seeds, databases, OAuth state, caches, and test artifacts are excluded.

The isolated affected backend suite, including specialist routing, passed
360 tests with two opt-in browser tests skipped in 134.78 seconds. It uses the
existing installed Python dependencies with the isolated worktree's source.

The isolated frontend suite passed all 294 tests across 36 files in 18.44 seconds,
and its production build passed in 1.02 seconds. The successful Vitest run used
`--maxWorkers=2 --testTimeout=15000` with jsdom and the existing installed
dependencies. Earlier runs hit cold-import and HTML-parser five-second timeouts
under parallel load; the final run had no failures or contract mismatches.
`git diff --check` also passed.

The original checkout's configured API and Vite UI were started, followed by
the Docker-backed Honcho memory stack. HTTP checks returned 200 for API health,
the served production UI source, Honcho health, and the creator endpoint. The
creator automation completed an actual scheduled run with eight feed attempts,
eight successful API fallback checks, and zero delivered historical uploads.
That run brought baseline coverage to 16 of 20 selected creators. This proves
startup and collection, while real future-upload delivery remains unverified.

## Follow-up live QA and CI repair

The running creator API returned uncached, typed reads with a median latency
of 93.46 ms across five requests (maximum 185.09 ms). Invalid limits returned
HTTP 422. The live App Action completed eight feed attempts and eight successful
connected API fallbacks, bringing all 20 selected creators to a quiet baseline;
status became `ready` with no warnings and no historical notifications. A
subsequent run through the real Automation API completed with zero additional
requests or notifications, confirming the shared rolling budget.

Live specialist QA exposed two bugs: saved baseline uploads could ignore title
topic rules, and quiet inferred creators could precede active creators in a
bounded response. Reads now apply active-channel and title-topic gates before
LIMIT, and active creators precede quiet candidates. New baselines mark
irrelevant entries suppressed. Regression tests cover legacy baseline rows,
small result limits, and inactive channels. The repeated UI question showed all
20 monitored creators; live API assertions confirmed excluded/former channels
were inactive and returned upload titles matched configured topic terms.

The isolated expanded affected suite passed 394 tests with two opt-in browser
checks skipped in 323.57 seconds. An earlier run failed four unrelated backup
fixture operations because temporary paths exceeded Windows path limits;
rerunning with shorter workspace temporary paths passed without source changes.
The separate App Action, book migration, and digest suites passed 87 tests in
42.82 seconds after correcting CI fixtures for creator permissions, additive
schema 15, and the new paused-by-default creator automation. The original CI
run had six such failures, with 2,837 tests passing and 27 skipped; production
permission enforcement was not relaxed. Repository-wide rerun results belong
to the new GitHub CI run, not these local affected-suite counts.

API, UI, and Honcho health returned HTTP 200. Installed Knowledge Core integrity
remained `ok`, and all 50,773 raw Takeout watch observations remained intact.
Crash-after-delivery recovery and notification deduplication passed in isolated
fixtures; real future-upload arrival remains unverified.

The actual UI **Refresh history** action failed closed with `page_changed`:
YouTube's current History page layout was not recognized, and no history was
imported. This is an outstanding browser-history integration limitation.
The creator service can poll uploads and assess already saved activity, but
continuous adaptation to new viewing is not established while fresh browser
history capture fails. No failed refresh was reported as a successful import.
