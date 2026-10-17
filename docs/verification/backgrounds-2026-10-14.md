# Pattern Waves and Particles verification — October 14, 2026

Added `pattern-waves` and `particles` to the existing production background
registry and Appearance picker. The final registry has eight live/animated
choices and three static scenes. Existing choices and the hidden ambient
fallback are retained.

## Selection failure and fix

The user reported “Unsupported background.” The backend's
`SettingsRuntimeActionService._validate_device_patch` had not been extended
alongside the frontend registry. A regression test dispatched every selectable
frontend ID through the actual action runtime: exactly the two new IDs failed
before the allowlist fix. The same tests passed afterward; unknown IDs still
fail without returning a preference patch.

The verified Vellum API process on port 8000 was restarted to load the fix.
Final browser QA used actual `/api/app-actions/dispatch` responses, rather than
fabricated device-settings receipts. The isolated browser clicked Particles,
Pattern Waves, and Particles again; each returned `status: applied`. Particles
remained selected after a reload. Both effects and their previews rendered in
headless Edge, with no page errors. See
[bounded results](backgrounds-2026-10-14/result.json).

## Checks performed

- Frontend Vitest suite: **406 passed across 42 files**. Coverage includes async
  Pattern Waves unmount, unavailable OGL/WebGL fallback, reduced-motion still
  frames and GPU cleanup, persisted device receipts, and the action-parity gate.
- Settings/action backend suites: **44 passed**, including every selectable
  background and rejection of an unknown ID.
- Required capabilities test: **1 passed**, 94 deselected; existing Starlette
  `BlockingPortal` deprecation warning.
- Production Vite build: **passed**, including the final contrast adjustment.
  The existing React/Babel entry continues to produce its non-module-script
  bundling warnings; the build copies the component sources through the existing
  static-asset step.
- Scoped `git diff --check`: **passed**.
- Mechanical design detector on the four new renderer files: no findings.

The first sandboxed frontend run was blocked by local socket/worker access;
rerunning outside the sandbox passed. The capabilities test likewise passed
outside the sandbox. These successful reruns are the results reported above.

## Visual evidence and limits

Desktop captures are 1440×1000; narrow captures are 390×844:

- [Pattern Waves desktop](backgrounds-2026-10-14/pattern-waves-desktop.png)
- [Pattern Waves narrow](backgrounds-2026-10-14/pattern-waves-mobile.png)
- [Particles desktop](backgrounds-2026-10-14/particles-desktop.png)
- [Particles narrow](backgrounds-2026-10-14/particles-mobile.png)
- [Picker desktop](backgrounds-2026-10-14/picker-desktop.png)
- [Picker narrow](backgrounds-2026-10-14/picker-mobile.png)

The visual review requested lower full-window Pattern Waves brightness for
foreground legibility. Full-window opacity is now 0.4; the preview retains 0.8.
The existing interface and design documents are preserved.

This is browser rendering and action validation. The physical Tauri desktop,
long-session GPU use, and alternate graphics drivers were not tested. Existing
narrow-screen composer/layout clipping is outside this background addition.
The external OGL loader is shared with Galaxy, so first-load Pattern Waves still
depends on that existing module source being reachable.
