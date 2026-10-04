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
separately from the passing final checks. The entire repository suite was not run.

Human/live-site gates remain for real sign-in, CAPTCHA, sites that detect
headless automation, DRM and native webview behavior. Chrome/Edge executable
overrides are configurable but only installed Brave was exercised here.
Full computer control is deferred.
