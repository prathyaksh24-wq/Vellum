# Browser homepage verification — 2026-10-07

The existing browser panel now has local native DOM homepages for Google, Brave,
DuckDuckGo, Startpage and SearXNG. Search-engine choice changes the illustrated
homepage, search hint and destination. Real websites continue through the existing
dedicated Brave owner. Preferences and shortcuts use the canonical browser typed
App Action and persist in its local session directory.

## Automated checks

| Check | Result |
| --- | --- |
| Frontend Vitest, full affected package | 36 files,291 tests passed |
| Vite production build | Passed; local browser assets copied into ui-dist |
| Browser backend suites | 77 passed,4 optional live tests skipped |
| Capability contract check | 1 passed |
| Browser smoke against disposable fixture | Passed, exit0 |
| Syntax checks for four browser smoke scripts | Passed |
| Impeccable detector, one bounded invocation | No findings |
| PNG prompt metadata scan | 7 raster assets,0 missing |

Backend command included viewport, session-live, YouTube-history, preferences,
planner-live, lifecycle and browser-agent tests. The one warning is Starlette's
existing deprecated BlockingPortal alias. Optional live planner/session gates
were not enabled; no public media was played during this design verification.

## Live fixture evidence

`frontend/scripts/browser-home-smoke.mjs` uses muted Brave with disposable profile,
backend8020 and frontend5180. It never points at the production profile. Its final
result is `.impeccable/review/browser-home-results.json`:

- Five engine homepages:918 ×861 page area after the incumbent sidebar's responsive
  collapse, no horizontal overflow. Initial expanded-sidebar captures were821px wide.
- Search: configured local SearXNG instance receives the encoded query through
  the typed navigation App Action.
- Page input: streamed screenshot coordinate click and typing reach the real
  fixture input field.
- Three blank tabs:255ms in the final run; address receives focus immediately.
  This measures local tab creation, not remote website load time.
- Shortcuts, expand/restore, close-tab and Escape: passed.
- Narrow viewport:390 ×844, panel x12/y12/366 ×820, homepage364px client and scroll
  width. Desktop and1920 ×1200 split captures are also available.
- Frontend page errors: none.
- User-reported menu clipping: new regression failed before the fix, then passed
  at1920 ×1200,1200 ×800 and390 ×844. All menu item centers hit their own buttons.
  Bounds clamp and scrolling protect the first-use setup state.
- User-requested centering: choosing unconfigured SearXNG no longer opens an inline
  form. Its title aligns with Google; explicit instance setup remains available.
  The final targeted frontend rerun passed18 tests and production build passed.

Screenshots and source comparisons are indexed by the root `design-qa.md` and
`docs/design/browser-home-approved.md`. An invalid intermediate capture set was
replaced after resetting an overflow-hidden root ancestor scrolled by automation.
The fixture profile restores sites on reopen, so setup explicitly selects Home.

## Runtime and environment

Production frontend5173 and backend8000 remain running. Backend launch pins
`PYTHONPATH` to this checkout's `backend` directory because the virtualenv's
editable installation points at an older checkout. Live production status
confirms the new preferences contract is served. Browser inspection helper failed
to initialize; the user explicitly approved muted Playwright in Brave as fallback.
QA sessions are closed through the browser owner; disposable servers are stopped
after review. No default Brave profile or user downloads are used by these tests.

## Delivery boundary

Native homepage input and engine switching avoid screenshot round trips. Public
pages retain the current streamed transport, so their performance and media
behavior depend on that implementation and the website. This run does not certify
CAPTCHA behavior or long YouTube playback. Native WebView2 setup and whole-Vellum
themes are deferred. No commit, PR or deployment is part of this local build.
