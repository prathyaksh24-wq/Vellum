# YouTube browser history

Open the YouTube connection dialog and select **Save URL and timezone**, then
**Open History**. Sign into the intended YouTube account/channel manually in
Vellum's browser. Its dedicated profile retains the session independently of
OAuth and independently of the everyday browser. Return to the YouTube dialog
and select **Refresh history**. The first successful refresh binds this reader
to the browser account. A later account change stops ingestion.

After verifying a manual refresh, optionally enable **YouTube history refresh**
in Automations. It defaults to paused, runs every 15 minutes when enabled, and
uses the existing automation scheduler. Keep History as the active browser tab
and resume agent control. A closed, paused, or user-controlled browser causes
refresh to skip; background refresh never opens a session or switches tabs.
The ordinary Automations controls manage schedule, pause, and run-now.

The reader uses a fixed extraction script on the History renderer, through the
existing serialized browser worker. It neither exports cookies nor exposes
arbitrary JavaScript to agents. No model is needed to extract entries. Sources,
private observations, account binding, and refresh state use Knowledge Core.
The YouTube specialist retrieves saved browser and Takeout history through its
existing capability, with provenance and freshness retained.

## Coverage and failure behavior

- Each refresh reads at most 100 currently loaded standard video entries. It
  does not claim complete account history, Shorts coverage, exact watch time,
  watch duration, or repeat-play counts.
- English Today/Yesterday headings use the timezone saved from the UI. Explicit
  supported dates retain day precision. Unknown/localized headings remain in
  the latest snapshot with unknown dates; they do not become fabricated events.
- Dated records represent a video's presence on a day, not a count of watches.
  Repeated refreshes do not duplicate those records. Displayed overlap with
  precise Takeout entries prefers the archive evidence. Browser observations
  remain separate from the existing precise watch-event trend projection.
- Sign-in, account changes, unknown layouts, empty/paused history, and reader
  failures are explicit. Failure never erases previous records or advances the
  last successful refresh. Source deletions are not mirrored automatically.
- The configured URL must be an HTTPS YouTube `/feed/` URL. Correcting the URL
  can repair address changes; renderer changes require a reader update.

## Validation

Deterministic tests cover duplicate refreshes, privacy, unknown dates, timezone
boundaries, account switches, URL validation, failure freshness, typed status,
and background ownership. A disposable Chromium DOM test verifies extraction
and the login/layout classifiers. Live Google sign-in and current YouTube DOM
must also be checked with a real account; fixtures do not establish that gate.
