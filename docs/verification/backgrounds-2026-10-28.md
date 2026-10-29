# Original DVK motion backgrounds — October 28, 2026

Added Nimbus, Daybreak, Eclipse, Dusk, Meadow, and Stratosphere to the production
Appearance registry and the existing device-settings allowlist. Appearance now
offers fourteen live/animated options and three static scenes.

The six original scene images, small previews, and Meadow depth map are bundled
locally. The vertex/fragment shaders are preserved verbatim in
`components/dvk-motion-shaders.js`; source URLs and hashes are recorded in
`assets/backgrounds/dvk/provenance.json`. The adapter changes canvas ownership,
loading/fallback, and resource lifecycle only. No visual shader, texture, crop,
animation coefficient, filtering, or full-scene resolution was redesigned.

## Fidelity and browser verification

Headless Edge rendered each actual adapter and each unmodified original script
at 960 × 640, device pixel ratio 1, animation time 7.25 seconds, and the centered
pointer. All six screenshot pairs had **identical pixels**. This is a fixed-time
visual comparison, not a claim about every graphics driver or every frame.

The production Vite page was also checked at 1440 × 1000 and 390 × 844.
All six Appearance selections returned `applied` receipts from the real
`AppActionRuntime` and `SettingsRuntimeActionService` in a disposable fixture.
Stratosphere remained selected and rendered after reload. Each hover preview
rendered, and the browser reported no page errors.

The fixture extends `backend/tests/action_parity_live_server.py` with the real
settings-runtime handler. Account status is a synthetic guest response; no
provider accounts, model calls, or user profile were used. This does not claim
acceptance in the user's running desktop/backend process.

- [Picker, desktop](backgrounds-2026-10-28/picker-desktop.png)
- [Picker, narrow](backgrounds-2026-10-28/picker-narrow.png)
- [Nimbus in Vellum](backgrounds-2026-10-28/nimbus-desktop.png)
- [Stratosphere, narrow](backgrounds-2026-10-28/stratosphere-narrow.png)
- [Receipts and comparison results](backgrounds-2026-10-28/result.json)

The existing narrow Vellum greeting can clip; this addition does not change
that layout. Settings uses its current scrollable narrow picker.

## Automated checks

- Background suites: **29 passed**. Includes source/asset hashes, unavailable
  WebGL, shader failure, reduced-motion still frames, visibility/offscreen and
  explicit pause, Meadow map loading/failure, cleanup, late image callbacks,
  fresh canvases on scene switches, original small previews, and device-local
  receipt persistence for all six IDs.
- Settings-runtime backend suite: **36 passed**. Its registry-driven test sends
  every selectable frontend ID through the real action dispatcher. Pytest
  reported a cache-directory permission warning.
- Production Vite build: **passed** after the final change. Every original
  image, preview, and Meadow map is present in the output. Existing non-module
  script, CSS syntax, and bundle-size warnings remain. The first sandboxed build
  failed resolving a Radix subpath; the outside-sandbox build passed.
- Full frontend suite: **698 passed, 7 failed**, across 77 files. Four stale
  source assertions concern chat script version tags, Discord installation,
  plugin settings wording, and conversation scrolling. Two Action Parity
  assertions report existing main-page/books handler drift. Removing this
  task's additions in memory produces the same main-page handler fingerprint
  (936 handlers), and all four missing strings are also missing in that
  reconstructed pre-task source. Existing fingerprints were not refreshed.
  The seventh failure was a routing-test timeout under parallel load; the
  routing suite passed **3/3** when run alone.
- Scoped `git diff --check`: **passed**.

The new decorative component is registered in the served-source Action Parity
scanner with zero visual state-changing handlers. Selection continues through
the existing background card and device-settings App Action.

Sandbox restrictions initially prevented frontend temporary-file renames and
backend temporary-vault creation. Successful runs above used the normal host
environment. Physical desktop use, long-session GPU behavior, and alternate
graphics drivers were not checked. Restart the running backend and reload the
app to load the new settings IDs and frontend components.
