# YouTube browser history verification — 2026-10-07

The YouTube specialist can refresh the signed-in dedicated-browser account's
recent watch history through the existing serialized Playwright owner. Overview
and chat expose `youtube.history.refresh` through the App Action dispatcher.
Questions use the specialist-only `youtube.watch_history` capability. Reads use
a temporary background tab, close it on success/failure, and preserve the visible
page. Browser status distinguishes background reads from foreground presentation.

Knowledge Core stores each account's latest bounded snapshot under a hashed
browser account identity, with `private_local_only` sensitivity and `deny_raw`
external policy. No cookies or raw account identifier are returned to the model.
Google OAuth likes/subscriptions and explicit Takeout archives retain their own
sources. Account changes and read failures do not substitute older data.

Validation:

- 166 backend checks passed across browser history, account capabilities, request
  interpretation, liked intents, OAuth connector/API and specialist regression
  suites. Coverage includes account isolation, sign-out/read failures, temporary
  tab cleanup, displayed-link retention, creator filters and specialist authority.
- The staged feature snapshot passed 157 checks with one expected skip for the
  separate profile-execution module, which is outside this commit. Three added
  argument-validation cases also passed in the 20-check browser-history suite.
- 16 frontend checks passed across history controls, actual classic/modern DOM
  extraction and served-handler App Action parity. Background session discovery
  preserves panel state; explicitly opening the same session remains available.
- Production Vite build passed. Existing classic-script bundling warnings remain.
- Live refresh read 11 recent rendered entries from the signed-in browser account.
  Live selected-specialist chat returned three requested videos, the exact second
  video's link and three channel names restricted to Yesterday.
- The real visible Refresh history control returned a verified local receipt and
  kept the Browser panel closed, using an isolated UI QA profile and the canonical
  backend browser account. The user's browser profile was preserved.
- A live “can u see my watch history” chat request also answered from the browser
  account while keeping the panel closed.

Local inference used the installed Gemma 4 12B model; the earlier configured
Qwen 3.5 9B model was absent from the local server. The local request interpreter
has a bounded 60-second deadline and reports timeouts explicitly. Exact ordinal
links resolve from the displayed list without another inference call.

Coverage is up to 100 recent rendered entries, retaining YouTube's day labels.
This is not an all-time watch count or a ledger of precise timestamps, durations
or repeat views. Only Today/Yesterday filters are currently supported. Refreshes
are on demand; continuous monitoring and long-term browser-history analytics
are outside this implementation.
