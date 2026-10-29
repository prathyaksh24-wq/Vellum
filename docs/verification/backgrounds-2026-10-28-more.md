# Nine more original DVK backgrounds — October 28, 2026

Added Cloudline, Grotto, Evergreen, Sunset Ridge, Orbit ASCII, Twilight, Riptide,
Seascape, and Bokeh to the existing Appearance registry and device-settings
allowlist. Appearance now offers 23 live/animated choices and three static
scenes. All earlier backgrounds remain available.

## Original rendering behavior

All original visual shaders are retained verbatim. The original images, depth
maps, sky plates, and glyph atlas are bundled locally, with source URLs and
SHA-256 hashes in `assets/backgrounds/dvk/provenance.json`.

- Cloudline and Seascape use their original WebGL1 shaders, 0.5/0.7 CSS-pixel
  render scales, preview scaling, pointer smoothing, and reduced-motion time.
- Grotto and Evergreen use the supplied depth maps.
- Sunset Ridge uses its depth map and clean sky plate, including `sky_s.jpg`
  for previews.
- Orbit ASCII uses the original scene and glyph shaders, 27-glyph atlas,
  12-pixel cells, original framebuffer precision, and original filtering.
  Both programs and the framebuffer are released on scene changes/unmount.
- Twilight, Riptide, and Bokeh use their original image-animation shaders.

The existing `DvkMotionBackground` owns every canvas, program, texture,
framebuffer, observer, and listener. It stops frames while paused, hidden, or
offscreen, renders still frames under reduced motion, and retains a usable
fallback when graphics or required textures are unavailable. The three
procedural/ASCII picker posters were captured from the original scripts at
640 × 400 and animation time 20 seconds. Other cards use original small images.
No dependency or remote runtime fetch was added.

## Browser evidence

Headless Edge rendered all fifteen DVK adapters and their unmodified original
scripts at 960 × 640, device pixel ratio 1, animation time 7.25 seconds, and a
centered pointer. **Every screenshot pair had identical pixels**, including
the six backgrounds from the earlier batch. This comparison verifies that
fixed sample on this graphics environment, rather than every frame/driver.

The real production Vite page was checked at 1440 × 1000 and 390 × 844. All
nine new selections returned `applied` receipts through `AppActionRuntime` and
`SettingsRuntimeActionService`. All hover previews rendered, Bokeh persisted
and rendered after reload, and no page errors were reported.

The disposable fixture extends `backend/tests/action_parity_live_server.py`
with the real settings-runtime handler. Account status is a synthetic guest
response. No user profile, provider account, model call, or production desktop
process was used.

- [Desktop picker](backgrounds-2026-10-28-more/picker-desktop.png)
- [Narrow picker](backgrounds-2026-10-28-more/picker-narrow.png)
- [Cloudline in Vellum](backgrounds-2026-10-28-more/cloudline-desktop.png)
- [Bokeh, narrow](backgrounds-2026-10-28-more/bokeh-narrow.png)
- [Selection receipts and all pixel comparisons](backgrounds-2026-10-28-more/result.json)

## Automated verification

- Background suites: **55 passed**. Coverage includes original shader/asset
  hashes for all fifteen scenes, device-local receipt persistence for every
  new ID, required depth/sky loading, procedural context/scale/still time,
  ASCII two-pass drawing, atlas failure, framebuffer cleanup, unavailable
  graphics, shader failure, visibility/pause, reduced motion, fresh canvases
  on scene changes, and late image callbacks.
- Settings-runtime backend suite: **45 passed**, including actual dispatch
  of every selectable frontend background and rejection of an unknown ID.
- Full frontend suite: **732 passed, 4 failed**. The four existing stale
  source assertions concern conversation scrolling, versioned chat script
  tags, Discord installation, and plugin-settings wording. None of those
  strings is changed by this batch. Action Parity and routing checks pass.
- Production Vite build: **passed**, retaining existing non-module-script,
  CSS syntax, and bundle-size warnings. All new original assets and posters
  are packaged under `ui-dist/assets/backgrounds/dvk/`.
- Scoped `git diff --check`: **passed**.

Physical desktop use, long-session GPU behavior, and alternate graphics
drivers were not tested. Restart the backend and reload Vellum to load the
new background IDs and renderer metadata in the running app.

## Live rejection and recovery

The user subsequently reported `Unsupported background.` for all nine new
choices. The real API on `127.0.0.1:8000` reproduced the exact failure for
Cloudline: `status: failed`, `INVALID_ACTION_ARGUMENTS`, and `Unsupported
background.` The live workspace endpoint confirmed the canonical checkout.
The API process had started at 12:59 IST, before the settings allowlist file
was updated at 13:14 IST, so its imported background IDs were stale.

Restarted only the verified API process through `scripts/start-api.ps1`.
The API health check passed, and the same direct HTTP action check returned
`status: applied` and the correct `device_settings_patch.values.background`
for all nine IDs. These checks used a separate diagnostic device snapshot
and did not apply receipts to the user's UI or change its selected background.
The existing UI process was left running. This verifies the production API
rejection is fixed; the user's physical desktop clicks were not automated.
