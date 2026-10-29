# YouTube browser history

Sign into the intended YouTube account/channel once in Vellum's Browser. Its
application-owned profile retains that session independently of Google OAuth
and your everyday browser. Select **Refresh history** in the YouTube overview,
chat, or connection dialog. Current watch-history questions use the same fresh
reader. They do not substitute an old import or a public video search on failure.

Refresh creates a temporary background tab, reads the configured History URL,
then closes the tab and restores the user's existing page and activity. It can
start the owned browser quietly from its saved profile. It does not present the
Browser panel. Paused or user-controlled sessions skip the read. **Open History**
remains an explicit foreground action for signing in or inspecting the page.

Enable **YouTube history refresh** in Automations for continuous accumulation.
It defaults to paused and runs every 15 minutes when enabled while Vellum's
backend is running. Schedule, pause/resume, and run-now use the existing
Automation owner. Existing user-edited schedules and states are preserved.
Sign-in or parser failures appear in history status and fail the automation run;
manual pause/takeover skips it. There is no second scheduler or database.

The connection dialog's **Save URL and timezone** sets a validated HTTPS YouTube
`/feed/` URL and an IANA timezone. On the first read without explicit settings,
the browser timezone resolves Today/Yesterday headings. Renderer recognition
still requires YouTube's History layout; changing a URL does not repair a changed
DOM. The extraction script is fixed, with no agent-supplied JavaScript, cookies,
credentials, or network interception.

## Persistence, accounts and coverage

- Each successful read captures at most 100 recent entries, including supported
  standard-video and Shorts cards. This is a page limit, not a cap on the saved
  history. Six scrolls and a bounded reader deadline limit each read.
- One current snapshot per browser account and durable dated observations use
  the existing Knowledge Core ingestion jobs, cursors, source versions and
  observation store. Raw history is `private_local_only` with `deny_raw` egress.
  It is not promoted automatically into permanent shared memories or preferences.
- A saved observation means a video's presence on a particular day. The identity
  is account + video ID + resolved day. Refreshing the same row again cannot
  duplicate it. Videos disappearing from the newest page remain in saved dated
  history. A new day can create another presence record, without implying an
  exact watch timestamp, duration, or number of repeat plays.
- Unknown/localized dates stay in the latest snapshot only. They do not become
  fabricated dated events or grow the durable count on every refresh.
- Account changes between reads select that account's separate source and saved
  records. Returning to an earlier account restores its accumulated history.
  A change during a read is rejected. Legacy account hashes remain stable.
  Browser and OAuth/Takeout identities are separate and never merged implicitly.
- Saved retrieval filters by the current account's source before counting and
  pagination. Creator filtering sees all saved pages before the display limit.
  Saved coverage is `accumulated_recent_pages`, not complete lifetime history.
- Sign-out, missing identity, unknown layout, storage failures, pause/takeover,
  and malformed responses never return old data as a successful fresh read.
  Failures preserve the last successful timestamp and account cursor; ingestion
  errors retain diagnostics. An explicit saved-history read reports freshness.
  A valid empty page saves an empty latest snapshot and retains prior dated rows.
  YouTube history deletions are not mirrored automatically into local evidence.

The YouTube specialist retrieves the saved evidence through its existing local
history/personal-context capabilities. Current history questions remain fresh
browser reads; archive questions retain Takeout provenance. Raw browser history
cannot be read into an external specialist model. Other agents use the existing
bounded, attributed specialist handoff, subject to their memory policies.

## Validation

Tests cover repeated refreshes, changing page windows, timezone/day rollover,
account switching and isolation, more than 500 accumulated records, failures,
empty pages, cursor preservation, concurrent refresh prevention, cloud-model
blocking, and scheduled execution. DOM fixtures cover modern plain-text creators,
classic channel links, Shorts and exclusion of unrelated recommendations.
Disposable Chromium checks validate temporary-tab cleanup and foreground-page
preservation. A signed-in live account and enabled scheduler still require runtime
acceptance after this draft is integrated; fixtures do not establish that gate.
