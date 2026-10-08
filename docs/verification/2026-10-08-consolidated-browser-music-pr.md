# Consolidated branch verification — 2026-10-08

Branch: `codex/browser-local-preview`. Draft PR: #214.

This branch includes the approved five browser homepages, owned Brave session
repairs, MusicAgent/Spotify changes, and YouTube account/history follow-ups.
It preserves the specialist runtime and configured history integration already
on main. Main at `14405150ccabc23cb6e792347eae8d2fc2a1d542` was merged without
rewriting history; the merge commit is `32c2deb`.

## Checks on the merged code

- Full backend suite: **2,798 passed, seven skipped**, one existing Starlette
  deprecation warning. Completed after the original-song guard and fixture fixes.
- Frontend: **292 passed across 36 files**.
- Production Vite build: **passed**. Existing classic-script bundling warnings
  remain; the build copies the served runtime assets through the existing plugin.
- Focused browser/music/profile/history suites: **371 passed, one skipped**.
- History/OAuth/action-parity merge checks: **49 passed, one skipped**.
- Regression rerun after the media corrections: **203 passed, one skipped**.
- No unresolved merge entries or whitespace errors. A changed-source credential
  pattern check passed; this is not a full gitleaks scan.

The local backend harness disables only the optional live Honcho client before
pytest starts. It pins imports to this checkout's `backend` directory and uses
`-p no:cacheprovider` with a short temporary base under Windows TEMP. The shorter
path avoids Windows path-length failures and the checkout's transient file-access
errors. Production Honcho configuration and code were not changed.

Two older media tests now use the intended current-browser history fixture and
confident unique-title behavior. An explicit original-song correction requires
additional artist evidence when the catalog returns only one artist; it cannot
silently replay the same unverified recording. Worker regression tests preserve
fresh temporary-tab reads and the closed/busy boundaries of configured refresh.

## Delivery boundary

Project source, tests, documentation and intentional browser assets are committed.
Runtime skill state, scratch captures, logs, databases and web caches stay local.
Draft #213 contains overlapping YouTube account/history work; #214 records that
relationship. GitHub CI runs independently of these local checks.

No public video playback QA was repeated for this publication step. Earlier live
browser evidence remains in the scoped verification documents. Native WebView2
setup and whole-Vellum themes are deferred; real websites retain the current
streamed Brave transport.
