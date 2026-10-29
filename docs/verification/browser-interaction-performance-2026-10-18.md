# Browser search and rendering verification — 2026-10-18

## Reported behavior and changes

The saved browser chat inspected for this repair requested an NBA search and received
separate confirmations for typing and clicking Google Search. Saved browser
settings already allowed routine interactions. The sensitivity check treated
Google's hidden image-upload input as making the whole form sensitive. Search
fields, suggestions, and Search submit controls now retain routine handling in
such forms. Actual file/password controls and the other sensitive checks remain.

BrowserAgent now uses visible search controls for search requests, rejects
constructed article/results URLs, and requires observed typing and submission
before accepting completion. Explicit user URLs retain direct navigation.
Named-site searches route without a browser keyword, and interactive follow-ups
stay in an established browser chat. Existing addresses are reused instead of
reloaded or duplicated. Changing-target retries reset after successful actions.

New native views start with a usable 1280 × 800 viewport, before UI mounting.
Previously their zero-size initial viewport could place page controls at negative
coordinates, producing misleading changing-control failures. Native bounds then
follow the actual panel. Divider drags prepare and decode one page capture before
detaching the view; the capture stretches through the gesture and the real page
returns on release. Parent status refreshes no longer cancel a held drag.

## Real-browser checks

- The muted disposable Electron fixture ran the real BrowserAgent and canonical
  browser capabilities with a deterministic planner. It rejected a guessed
  article URL, opened the fixture homepage, typed `jailer`, observed an async
  suggestion, and clicked its actual link. The fixture includes a hidden upload
  input to exercise the search-form classification.
- The existing native actions, cursor, tabs, fullscreen exit, profile cookie
  isolation, cookie clearing, downloads, and no-stream assertions passed.
- In the running desktop app, a held divider drag retained a decoded, visible
  page image. Releasing restored the native page with matching panel dimensions.
- Through `/api/chat`, the selected local `ollama/gemma4:12b` model completed
  “Search Wikipedia for Jailer 2.” It used BrowserAgent without a browser keyword,
  typed and selected the page, and reached `/wiki/Jailer_2` without routine
  confirmation. The request used `store:false` and took approximately 56 seconds.
- An earlier live Google route typed and submitted successfully but reached
  Google's unusual-traffic CAPTCHA. The agent reported the block and stopped;
  it did not bypass the challenge. Wikipedia was tested directly afterward.

## Background measurements

Recorded in the same running Electron workspace with two-second requestAnimationFrame
samples and temporary draw-call counters. Galaxy's canvas is capped at about
600,000 pixels and 30 animation draws per second. UI frame rate remains independent.
Settings pauses the selected backdrop. Appearance initially uses eight bundled
thumbnails captured from Vellum's own renderers (about 195 KB total); hover/focus
mounts a live preview and leaving releases it. The registry IDs and palettes stay
the same.

| State | Before: frames in 2 s / p95 gap | After: frames in 2 s / p95 gap |
| --- | --- | --- |
| Galaxy workspace | 29 / 124 ms | 117 / 18 ms |
| Galaxy with Appearance open | 29 / 84 ms | 114 / 33 ms |
| Static Ember Clouds workspace | 121 / 17 ms | 121 / 18 ms |

The optimized Appearance sample performed zero continuous WebGL draw calls while
idle. The previous Galaxy-with-Appearance sample performed 174. These short local
measurements are not a device-wide benchmark or a guarantee during model inference.

## Regression and package checks

- Browser-focused backend checks: 148 passed, one skipped; the final shortened
  agent prompt passed all 26 prompt checks.
- Final browser chat-flow and specialist-dispatcher regression run: 128 passed,
  including browser follow-ups taking priority over topic matching while factual
  questions can return to a specialist.
- Frontend full suite: 475 passed. After the final divider lifecycle adjustment,
  all 39 affected browser, background, and action-parity checks passed again.
- Desktop Node checks: seven passed. The production UI build and Electron Forge
  Windows x64 ZIP packaging completed successfully.

## Remaining limitations

Native rendering does not accelerate model planning; the live Gemma lookup still
took about a minute. CAPTCHA, sensitive actions, and explicit ask/block settings
retain their policy paths. No extension, DRM, or long-video claim is made here.
No Git commit, push, or PR was created. Unrelated working-tree changes remain.
