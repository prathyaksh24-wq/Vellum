# YouTube notifications after rejected Google authorization

Verified 22 October 2026, approximately 11:11–11:20 IST. No Git publication.

## Cause and live evidence

The backend was running and the hosted receiver returned HTTP 200, with 297 of
297 desired targets active, current incoming events, and no host warnings. Local
DNS resolved Google and Cloudflare hosts. Google connection status was
`authorization_required`; a stored-grant refresh attempt failed with
`YouTubeAuthError`. This establishes rejected authorization, not its specific
revocation/expiry cause. The Google Cloud project's OAuth publishing status was
not inspected. The latest saved notification before recovery was from 19 October.

151 queued uploads could not pass video-length verification. Push status exposed
only generic duration/subscription warnings. The user reconnected the same
MindBodyAwaken channel. Connection status became ready, but provider and
per-video retry timers still delayed processing. A regression test reproduced
both repeated attempts for a known rejected grant and failure to release these
timers after reconnection.

## Fix

- Add explicit `authorization_required` to typed push status, prioritize that
  state, and show a sanitized reconnect warning.
- Do not reserve another duration unit or call Google for a grant already known
  to require authorization. The call that first discovers rejection still counts.
- After a successful OAuth callback, release failed duration and subscription
  timers only for the explicitly linked account. Preserve counters, cache,
  history, account linkage, duration threshold, relevance, frequency and exclusions.
- Persist a bounded account-scoped recovery marker in existing Knowledge Core
  cursors if the tracking worker is busy; the normal worker retries it.
- Keep a valid Google connection successful if local queue recovery is deferred;
  return a content-free deferred-check message instead of an OAuth failure.

The canonical recovery method was run for the user's renewed grant, then the
verified backend process was restarted through `scripts/start-api.ps1` to load
the fix. No tokens or provider response bodies were printed or committed.

## Verification

- 135 affected YouTube, OAuth and notification backend tests passed.
- Capability discovery: 1 passed, 96 deselected.
- Rendered reconnect, inbox and plugin adapter frontend checks: 23 passed in
  three files. No frontend source changes or new full production build claimed.
- Python compilation and scoped whitespace checks passed; existing CRLF and
  Starlette/AnyIO deprecation warnings remained.
- After reconnecting, 29 new unread notifications were observed at 11:16 IST,
  including Nightcap, GothamChess and NFL. This was real provider-backed catch-up,
  not synthetic callbacks. Sampled video durations were 2009, 1263 and 514 seconds.
- Final API at 11:20 IST: ready, authorization_required false, 297/297 targets
  active, five queued uploads, no warnings, hosted sync current. The unread count
  subsequently changed; the earlier count is a timestamped observation, not a
  promise of the current unread total. Remaining unknown-duration videos do not
  bypass the long-form gate.
- Saved History was checked after restart: today's delivered records remained
  present with read receipts (including Ken and Chess.com at 11:17 IST). The
  empty Recent view reflected marked-read notifications, not lost delivery.

External Google OAuth apps in Testing receive seven-day refresh tokens for
YouTube scopes; that is a possible recurring cause, not a verified project
setting in this incident. Reference:
https://developers.google.com/identity/protocols/oauth2/ . Google may also revoke
grants for other reasons; the application cannot promise grants never expire.
