# Browser use verification — 2026-10-04

Baseline: `4b63bbe` (`origin/main` at implementation time).

- Core affected backend suites: **162 passed**, covering browser permissions,
  delegation, confirmation, local routing, profiles, shared capabilities,
  legacy MCP compatibility and installed Brave. Includes changed-DOM
  confirmation rejection, stale preview inputs, last-tab recovery, shutdown
  and a download after reopening the same dedicated profile.
- All affected App Action suites: **204 passed**. This overlaps the core run;
  these counts are separate runs, not an aggregate unique-test count.
- Focused frontend/backend capability contract: **1 passed**, 75 deselected.
- Complete frontend tests: **31 files, 224 tests passed**. Production Vite build
  passed; existing classic-script warnings remain.
- Installed `ollama/gemma4:12b` + BrowserAgent + actual dedicated Brave on a
  disposable localhost page: **1 passed**. The model navigated to the requested
  page and reported its observed heading. No cloud inference was used.
- Live served UI smoke: **two runs passed using the same Brave profile**,
  covering More disclosure, scaled click/keyboard input,
  ownership controls, tabs, a new saved download, close/reopen and overflow at
  1536×1024, 1440×1000 and 390×844. Test fixture content is synthetic.
- Dependency consistency: `pip check` passed. OSV queries for installed
  Playwright 1.63.0, pyee 13.0.1 and greenlet 3.5.6 returned no advisories.
  This is a focused dependency audit, not an audit of the entire environment.
- `git diff --check` passed.

An earlier broader run had 259 passes and one timing-dependent failure in
`test_confirmation_rejects_an_automation_that_changed_after_review`. That failure
was reproduced with the unmodified baseline App Action runtime: a same-second
description edit can keep the automation confirmation binding unchanged. The
final 204-test App Action run includes this test and passed. Browser code does
not modify that automation binding; the earlier baseline behavior is recorded
separately from the passing initial checks. The initial implementation did not
run the entire repository suite locally.

## CI follow-up

The first Linux CI run reported 20 failures: three prompt contracts and 17
legacy MCP tests. Worker shutdown retained the dedicated transport selection,
so later calls in the same process could not start a fresh legacy session.
The new regression failed before the fix and passed afterward. Session close
still keeps dedicated ownership; worker shutdown now releases that selection.

Prompt tests now enforce BrowserAgent delegation and the compact manifest's
actual fields instead of expecting direct main-agent browser access or banning
the word `tools` from descriptions. The system prompt stays below its existing
7,500-character budget. CodeQL's incomplete-URL-substring alert was on a test
assertion; checking the complete delegated goal/context strengthens that test
and removes the ambiguous substring operation.

- Prompt, BrowserAgent and MCP suites after the fix: **94 passed**.
- Installed Brave followed by legacy MCP tests in one process: **51 passed**.
- A Windows full-suite reproduction before the fix also encountered book/document
  storage, backup-path and coding-fixture failures absent from the original
  Linux CI run; that local run was not a passing full-suite check.
- CI supports manual dispatch of the existing checks against a selected branch
  when an update does not automatically produce a run. Latest Linux CI and
  CodeQL status are recorded on the draft PR.

Human/live-site gates remain for real sign-in, CAPTCHA, sites that detect
headless automation, DRM and native webview behavior. Chrome/Edge executable
overrides are configurable but only installed Brave was exercised here.
Full computer control is deferred.

## Sidebar startup regression

The Browser entry could appear before the initial browser status response.
Its handler used the initial `available: false` state, so the first click
showed a closed panel without launching. It now reads fresh status through the
existing adapter before deciding whether to open the session.

The real Brave UI smoke holds the first status response while clicking Browser.
The regression failed on the original handler with no open action dispatched.
Follow-up validation checks one-click launch and the existing controls, downloads
and desktop/mobile layout against disposable fixtures, separately from local
server activation. Latest results are recorded on the follow-up PR.

The sidebar failure path also called the toast state as a function. A rejected
launch now uses the existing `pushToast` helper. The smoke rejects an open receipt
and checks that its message appears without a page error, then retries normally.

## Interrupted cleanup regression

Cancelling cleanup after a CDP disconnection could leave the owned Brave process
alive while losing its handle. A subsequent launch then failed because that
process still held the dedicated profile. Overlapping close calls could also
return before the first cleanup finished.

The existing transport now keeps one shielded cleanup task. Close and reopen
callers wait for that task to finish releasing the process and Playwright driver.
The original failure was reproduced with a disposable real Brave profile, and
the same interruption/reopen probe passed after the fix. Verification passed
78 browser/worker tests and both opt-in real Brave lifecycle tests. No default
browser profile or user downloads were used by these regression tests.
