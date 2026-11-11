# Original background brightness — 2026-11-11

The user reported that static and animated backgrounds were still covered by
a dark overlay. The background layer's contrast-based opacity limiter was
the cause: with a saved requested visibility of 0.4, the sampled cases rendered
at only 0.19–0.23 effective opacity. This changed the original scene pixels.

Background mode now sets the layer opacity to 1. Saved legacy visibility
settings, including zero, cannot dim or hide a scene. The visibility slider
and limiter are removed. Light-mode Galaxy inversion/multiply blending and
reduced-motion dimming are removed; reduced-motion lifecycle behavior remains.
Ambient orb, cursor glow, and dot-grid layers do not tint the selected scene.
Named themes still use a plain surface and unmount the scene renderer.
Existing text shadows and local composer/menu surfaces provide readability.
Source shaders, images, crop, and animation parameters are unchanged.

## Reproduction and verification

The added regression test `backgrounds retain full brightness despite
previously saved visibility settings` failed before the fix (`0` rather than
`1`). It now checks saved values 0, 0.4, and 1 in both modes. The mounted
background test also confirms that a legacy zero does not hide the renderer.

An isolated hidden Electron renderer compared the same source content directly
and through the production `AppBackground`, theme projection, and page CSS.
The static case uses the bundled Serenox Home image through the actual
`StaticImageBackground`. The canvas case uses an opaque, deterministic color
frame in the Galaxy container, so compositing is tested without shader timing
or a live provider dependency. Reference and wrapped content use matching
512 × 512 bounds. Before/after sources were retained in a local debug fixture.

| Content | Mode | Previous opacity | Previous changed pixels | Fixed changed pixels | Fixed maximum channel difference |
| --- | --- | --- | --- | --- | --- |
| Static image | Light | 0.21 | 262,144 | 0 | 0 |
| Static image | Dark | 0.23 | 262,144 | 0 | 0 |
| Canvas frame | Light | 0.21 | 262,144 | 0 | 0 |
| Canvas frame | Dark | 0.19 | 262,144 | 0 | 0 |

The screenshot bitmap has the same source colors after the fix in all four
cases. [Raw comparison results](background-brightness-2026-11-11/results.json),
[previous static rendering](background-brightness-2026-11-11/static-before.png),
and [fixed static rendering](background-brightness-2026-11-11/static-after.png)
record the check. This proves the scene compositing behavior; it is not a
walkthrough of every live WebGL effect in the user's running Vellum window.

All 109 focused frontend tests pass across the theme, device settings runtime,
Action Parity, terminal, React Bits background, and DVK background suites.
The theme selector fingerprint was reviewed: four visibility slider handlers
were removed and the single typed theme selection remains. There are no
backend behavior or schema changes in this correction. Earlier broader-suite
failures remain documented in the app theme verification report.

The production desktop build is copied to `desktop/resources/ui` after asset
verification. No server is restarted and no Git publication is performed.
The copied HTML and theme projection match the staged build byte for byte.
Entry SHA-256: `cf66d3e4123b1870e1ba9b8bb4c7d3f1a7bd802f0e1b1f6d43b82217fcb9d5a2`.

## Proposed pull request

**Title:** Preserve original static and animated background brightness

**Description:** Remove the contrast-based opacity limiter and visibility
slider that darkened selected backgrounds. Keep original scene colors in both
Light and Dark, ignore legacy visibility values, and retain app theme/background
exclusivity. Validate the fix with source-versus-wrapped pixel comparisons,
109 focused frontend tests, and the production desktop build. Native app
selection/reload remains an attended verification gap.

## Scoped publication validation

The publication branch was isolated from current main at `bcd72b1`; unrelated
local identity, voice, streaming, and workspace changes were excluded. The
109 focused frontend checks, 85 backend settings checks, and production desktop
build pass in that isolated checkout using the existing installed dependencies.
Action Parity validates the reviewed new theme control. The earlier development
results and desktop bundle hashes above describe the original local checkout.
Screenshots and pixel results are development rendering evidence, not a live
walkthrough of the isolated branch. Servers remain untouched.
