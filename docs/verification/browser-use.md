# Browser use verification — 2026-10-04

## Input, tabs and Sources drawer — 2026-10-06

Escape previously bubbled to the app's global panel-hide handler. Forwarding
Escape through CDP alone also failed to exit remote HTML fullscreen. The page
gesture now contains Escape and exits that document's fullscreen before
dispatching its page key. A real synthetic video keeps playing afterward.

Three user tabs initially took 12.419 seconds with four-second homepage loads.
Asynchronous loads alone were insufficient: status title reads and preview
attachment could still wait on an uncommitted document. The final live run
created three tabs in **269 ms** (657 ms with the later native-renderer launch),
with immediate empty address focus. Background
navigation no longer invalidates the visible frame; child-frame navigation
still invalidates agent confirmations without restarting that page's feed.

Both chat and specialist Sources handlers now explicitly select the existing
Workspace Layout `files` mode, in which the selected message's Activity drawer
renders. The live regression clicks Sources after using Browser, checks visible
source links, and verifies the dedicated session is still running.

Validation:

- Browser/worker/delegation suites including installed Brave: **95 passed**.
  This includes native-window hiding, exact child-announced endpoint validation,
  last-tab retention, backend termination and same-profile reopening.
- Focused browser/capability contract run: **21 passed**, 75 deselected.
- Complete frontend suite: **34 files, 263 tests passed**; production build
  passed with the existing classic-script warnings.
- `browser-responsiveness-smoke.mjs`: passed tab creation, immediate address
  focus, video fullscreen/Escape, continued playback, Alt+L/W and Sources.
- Existing `browser-session-smoke.mjs`: passed launch/readiness races, input,
  pause/resume, tabs, download, adaptive desktop/mobile viewport and close/reopen.
  It measured **69 ms** typed input latency and **21.95 preview frames/sec** on
  the local animation fixture. These are fixture measurements, not guarantees
  for arbitrary network sites or video frame rates.
  The native-renderer run measured 395 ms typing and 21.90 preview frames/sec.
- Native caption text was visually present in normal and fullscreen streamed
  frames of the local captioned-video fixture.

### YouTube launch compatibility correction

The public TED video `https://www.youtube.com/watch?v=iG9CE55wbtY` reproduced
empty captions with CC enabled and `Something went wrong. Refresh or try again
later.` after roughly a minute (the user measured 42 seconds). The caption response had HTTP 200 with a
zero-byte body. This happened in a disposable headless session, a normal
offscreen Brave comparison, and a narrowly scoped probe of Vellum's existing
signed-in session. The signed-in probe observed only that public video and
closed only its newly created tab; it did not read mail or cookies, reset login
state, or alter site-protection settings. The user reports the same video works
in regular Brave. The same failure also reproduced without screenshots or a
screencast, while the document remained visible/focused: streaming was not
necessary to trigger it.

A normal Brave launch on a chosen nonzero loopback CDP port restored nonempty
caption responses (59,007 bytes) and sustained playback to 95 seconds. The
production transport now uses that mode and hides only its own native windows.
The identical public-video gate then passed to 94.87 seconds with captions
visible in the streamed JPEG; the user's existing signed-in profile also passed
the cutoff with captions (92.80 seconds, no error). No user-agent spoofing, webdriver-script injection,
site-protection change, proxy or CAPTCHA bypass was added. These comparisons
establish a working launch configuration, not YouTube's internal rejection cause.

CDP attachment uses the exact websocket GUID announced by the newly spawned
child, validates loopback address and selected port, and fails closed on another
endpoint. The stderr pipe is discarded without logging content and remains
drained through process close. Closing the final tab creates a blank replacement
before closing it, since a normal native browser would otherwise exit. Preview
detach and browser-close awaits are bounded. Real Brave tests count zero visible
native windows for the owned PID and retain abrupt-backend cleanup coverage.

A disposable YouTube-only Shields comparison did not restore captions. It was
interrupted before a conclusive sustained-playback result; the test preference
was restored. An optional Edge comparison could not launch, so it is not a
passing media check. No production browser executable selection or Shields
settings were changed. These experiments do not establish the underlying
YouTube cause. Playback longer than the bounded gate and other videos remain
compatibility checks.

A strengthened real-YouTube fullscreen gate sustained playback to 97.19 seconds
with captions, but did not enter fullscreen through its coordinate click, so
that full gate failed. The synthetic video fullscreen/Escape regression passed;
actual YouTube fullscreen input remains an unverified gap. Overlapping diagnostic
videos disturbed the user. All QA APIs/UI sessions and disposable Brave processes
were stopped, and the explicitly disposable browser fixture now adds
`--mute-audio` by default. No further video probes were run afterward.

`browser-youtube-media-smoke.mjs` is an explicit public-site compatibility gate
using only the disposable fixture. It now exits unsuccessfully for missing
captions or failed sustained playback, rather than treating a completed probe
as a pass. QA-only request observations retain bounded category/status/body-size
metadata, without request URLs, headers, cookies or response content.

Ctrl+W/L/T are reserved by the outer web browser in this web UI; ordinary page
handlers cannot reliably intercept them. Panel Alt shortcuts are verified.
Native desktop setup remains deferred as requested.

## Launch after backend termination — 2026-10-05

Both sidebar and chat launches failed before any homepage navigation. The
canonical open action returned `The dedicated browser could not start.` while
an older Vellum-owned Brave process still held `data/browser-session/profile`
after its backend had exited. Gracefully closing that verified stale session
restored launch without accessing the user's daily Brave profile.

The Windows transport now owns an unnamed, non-inheritable job handle with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, assigning only its newly launched browser.
Normal cleanup releases the handle after graceful browser close; abrupt backend
termination closes it through the OS. The installed-Brave regression failed
before the change because the browser survived the killed backend. It now
verifies browser termination and reopening the same disposable profile.

- Browser permissions, lifecycle, installed Brave and legacy worker tests:
  **88 passed**. The strengthened same-profile reopen probe also passed.
- Full frontend suite: **260 passed**; production build passed.
- Actual served UI smoke passed sidebar launch with delayed initial readiness,
  rejected-launch messaging, manual input, tabs, downloads, close/reopen and
  desktop/mobile checks without page errors.
- The user's current API was verified to open the dedicated browser on Google's
  homepage and return a live JPEG frame. Google Search CAPTCHA compatibility
  remains separate from this process launch fix.

## Search detour and blank new tabs — 2026-10-05

Typing `google` or `youtube` dispatched a Google search instead of navigating
directly to the named website. The adapter and rendered address submission
regressions failed before the fix. Exact recognized site names now open their
destinations; ordinary search phrases still search Google. User-opened blank
sessions and new tabs show Google's homepage, while existing destinations and
explicit tab URLs are preserved. Agent transport startup remains neutral.

Real Brave validation used a disposable profile and the served panel. Google home
loaded without a challenge; `youtube`, `spotify`, `reddit` and `x` dispatched
their direct addresses. YouTube, Wikipedia and Spotify searches worked. Reddit
still returned a network-security block and X returned HTTP 403. Both initial
open and the New tab action showed Google's homepage.

A separate ordinary Google search (`youtube videos`) reproduced a challenge at
`www.google.com/sorry/index`. No CAPTCHA was solved or bypassed. Removing the
search detour fixes named-site navigation; it does not establish a fix for Google
Search's verification loop. Network reputation versus headless-session rejection
has not been isolated, and native setup remains deferred.

- Browser/capability backend checks: 37 passed, 74 deselected.
- Full frontend suite: 34 files, 260 tests passed; production build passed.
- Disposable live-site script and new-tab checks passed; site blocks above are
  recorded compatibility failures, not successful website access.

## Browser fit, direct gestures and live frames — 2026-10-05

The fixed 1280×800 screenshot and one-second refresh caused letterboxing and
delayed feedback. Page input was discarded until explicit takeover; rapid typing
issued a request and status read per character. The regression first failed with
no takeover or click dispatched. It now verifies automatic takeover, the original
click, batched text, and ordering around paste and Enter.

The canonical Playwright transport now caches Brave's changed screencast frames
and exposes them through a read-only, loopback-origin WebSocket. Viewport resize
and input retain `browser.session.control`; resize leaves agent ownership intact.
Takeover invalidates prepared agent actions while preserving unchanged frame
identity. A stale document cannot receive the original click after takeover.

- Browser/worker tests including installed Brave lifecycle and downloads:
  **85 passed**. Final browser, capability and visual Action contract run:
  **32 passed**, 74 deselected; these are separate, overlapping runs.
- Complete frontend suite after paste/composition ordering refinement:
  **34 files, 248 tests passed**.
  Production build passed with existing classic-script warnings.
- Final input/error recovery and handler gate: **24 tests passed**. Actual
  WebSocket rejection and read-only input handling, with viewport/cache tests:
  **10 passed**. Mechanical UI scan returned no findings; diff whitespace check
  passed. The full backend repository suite was not rerun for this scoped fix.
- Real served UI against disposable profiles: tabs, download saving, close/reopen,
  one-click takeover, batched typing and no outer overflow passed. Page aspect
  ratio matched the panel at 1536×1024, 1440×1000 and 390×844 without gray bands.
- The local moving-page fixture delivered **21.4 changed frames/second** over a
  two-second sample. “Hello Brave” reached the page in **179 ms** with one text
  request. These are fixture measurements, not site-wide performance guarantees.

An explicit public-site run used the same served panel and installed Brave with
a separate disposable profile. It did not sign in or use personal browser data:

| Website | Observed result |
| --- | --- |
| Wikipedia | Main Page rendered; page Search revealed its input and reached the Brave browser article through panel clicks and typing. |
| YouTube | Homepage rendered; native page search reached results for “Brave browser”. |
| Spotify | Public Web Player rendered; page search reached `/search/Brave%20browser`. Audio playback was not tested. |
| Reddit | Returned “You've been blocked by network security.” |
| X | Returned an HTTP 403 browser error page. |

Reddit and X remain compatibility failures for this tested session. This evidence
does not identify whether the block is due to network reputation or browser
automation, and does not establish that switching to a native webview will fix it.
Real account sign-in, DRM/media playback and native browser UI remain unverified.
Native desktop setup was deferred at the user's request; no Rust or C++ tools
were installed. The web UI still shows a live streamed Brave page, not a native
Brave window.

## Local recovery and address regression — 2026-10-05

The running backend returned failed receipts for both opening and closing its
stuck session. Its dedicated Brave process was still alive while status reported
the session closed. Recovery stopped only the verified application-owned process
and restarted the backend, preserving the saved profile. This operational
recovery does not establish a new cause beyond the existing lifecycle fixes.

Against the restarted backend, a real Brave UI probe closed the session, clicked
the served Vellum sidebar's Browser entry, and verified the visible panel, Ready
status and address field. A separate regression reproduced search text being
converted to `https://google`; the real address form now dispatches a Google
search URL through the existing App Action adapter.

- Affected browser, worker, YouTube OAuth/capability, API and visual-action
  suites: **182 passed**, two unrelated book tests deselected. This includes
  opt-in real Brave lifecycle and session checks.
- Complete frontend suite: **33 files, 247 tests passed**. Production build
  passed with the existing classic-script warnings.
- A live request through the selected YouTube agent returned connected-account
  liked-video titles for the original misspelled request, with memory storage
  disabled. The temporary QA conversation state was removed.
- PR #211's separate backend fixture corrections passed all six GitHub CI jobs.
  A local full-suite Windows run had unrelated book/storage/coding failures;
  it is not recorded as a passing full-suite run.

## Initial implementation verification

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

The five-engine native homepage build and its latest bounded evidence are recorded
in [the 2026-10-07 verification report](2026-10-07-browser-home.md).

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
