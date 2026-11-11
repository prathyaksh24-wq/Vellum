# App themes and bright-background readability — 2026-11-11

## Requested behavior and implementation

Ten community themes are available in one Settings → Appearance dropdown.
The Light/Dark toggle chooses the selected theme's variant. All ten are distinct; the older Matrix background is
an accent/background preset and remains separate from Matrix Green's complete
app palette. Existing static and animated background IDs are preserved.

The device settings owner now validates and merges `appearance` preferences.
The frontend persists only successful receipts through its existing device
snapshot and serializes device writes. Failed selections retain the saved
theme and expose a retryable error. The active profile maps onto existing app
CSS tokens; open xterm instances receive palette updates without reopening.
Named themes use a plain surface. The selected scene renderer is unmounted,
its animation resources are released, and ambient decorative layers are hidden.
The palette application bypasses the saved background's colors. Selecting any
background clears the app theme, even when reselecting the same scene. This
replacement rule is enforced by the device settings owner for UI and chat.
The chooser also sends that intent explicitly, so an already-running backend
that accepts the earlier appearance fields receives a complete update.

The existing `light_theme` and `dark_theme` fields are written together for
compatibility. A legacy split selection displays the named dark choice in both
modes, falling back to the named light choice if necessary. The next selection
synchronizes the stored fields. Contradictory split writes are rejected.

Source primary/secondary colors are adjusted where needed for readability.
Primary and secondary text retain at least 4.5:1 contrast on named theme
surfaces. Backgrounds now render at their original brightness, without the
initial contrast-based opacity limit or its slider. The legacy saved opacity
field is ignored. Text shadows and local composer/menu surfaces separate the
interface from the scene. See the later
[background fidelity correction](background-brightness-2026-11-11.md) for
before/after pixel checks. Vellum's bundled SN Pro and existing code fonts are retained; remote
fonts from the community samples are not loaded. Vendor artwork, embedded web
content, and user content retain their original colors.

## Source provenance

These exact source pages supplied the bundled light/dark CSS tokens. Source
and author metadata are retained in `app-theme-presets.js`; themes require no
runtime fetch from 21st.dev.

| Theme | Source |
| --- | --- |
| Matrix Green | https://21st.dev/@serafimcloud/themes/matrix-green |
| Zen Linen | https://21st.dev/@serafimcloud/themes/zen-linen |
| Catppuccin | https://21st.dev/@serafimcloud/themes/catppuccin |
| Twitter | https://21st.dev/@serafimcloud/themes/twitter |
| Vintage Paper | https://21st.dev/@serafimcloud/themes/vintage-paper |
| Quantum Rose | https://21st.dev/@serafimcloud/themes/quantum-rose |
| Cosmic Night | https://21st.dev/@serafimcloud/themes/cosmic-night |
| Sage Garden | https://21st.dev/@serafimcloud/themes/sage-garden |
| Sage Mist | https://21st.dev/@serafimcloud/themes/sage-mist |
| Cyberpunk Neon | https://21st.dev/@sh20raj/themes/cyberpunk-neon-1789321780521 |

## Verification

- Backend settings suite: 98 passed. Covers each new theme through the actual
  dispatcher, linked mode variants, replacement by every background (including
  the currently saved scene), background precedence in a combined patch,
  partial merge, unrelated preference preservation, invalid IDs,
  out-of-range opacity, unknown appearance keys, and conflicting split writes.
  Pytest reported a cache-directory permission warning; test assertions passed.
- Focused frontend checks after the brightness correction: 109 passed across six files. They cover all twenty
  palettes against black/white background extremes, text on panel/sidebar/menu/
  input/code surfaces, contrast on accent buttons, background/theme selection
  isolation, persisted theme reload and both variants, serialized writes and error recovery,
  actual single VSelect rendering, background renderer unmount/disposal and
  remount on return to background mode, terminal updates/disposal, background renderers,
  and reviewed Action Parity handler coverage. The surface check caught and
  corrected low-contrast secondary text on Catppuccin's dark popover.
- Production desktop Vite build succeeds. The existing large-chunk warning
  remains. Output is staged before being copied into the bundled UI; existing
  hashed assets are retained for already-open documents.
  The staged entry and theme scripts are verified against `desktop/resources/ui`
  after copying.
  The latest bundle identity is recorded with the background fidelity correction.
- Isolated Electron rendering checked the real theme settings component with
  the shared selector and CSS at desktop and narrow widths. This is component
  rendering evidence, not an attended walkthrough of the running Vellum app.
  [Light desktop rendering](app-themes-2026-11-11/theme-light.png) and
  [dark narrow rendering](app-themes-2026-11-11/theme-dark-narrow.png) show the
  current single chooser and plain Catppuccin surfaces. These use current theme
  settings and shared selector code; the sample title area is a rendering fixture.
- Impeccable's source detector returned no findings for this change.
- The focused capabilities endpoint check (`test_api.py -k capabilities`)
  produced no output after about four minutes and was interrupted. It is not
  counted as a pass.

The broad frontend run reported 762 passing and 85 failing tests across 88
files before the final parity inventory update. Two Action Parity failures
introduced here were corrected, and all thirteen parity checks pass in the
focused run. Other failures include stale full-entry rendering fixtures,
connector OAuth expectations, and unrelated workspace tests. Their baseline
status has not been exhaustively established; the full frontend suite is not
claimed green. The broader App Actions backend run reported 87 passing and
one failing test: `test_catalog_exposes_actions_and_registered_surface_contracts`
expects a surface set that omits the existing `chat-details` registration.

No server was started, stopped, or restarted for this task. Live native-app
selection/save/reload has not been verified. This correction reuses the earlier
appearance schema; the UI sends both linked fields and explicitly clears them
when choosing a background. The backend replacement rule for non-UI callers
takes effect when its updated implementation is loaded. No Git commit, push,
or PR was created.

## Proposed pull request

**Title:** Add app-wide themes with exclusive static and live backgrounds

**Description:** Add the ten requested 21st.dev palettes to Vellum's existing
Appearance settings with one chooser and Light/Dark variants. Persist validated
partial changes through the revisioned device settings action, serialize rapid
writes, and map the active palette across the app and open terminals. Keep
named themes on plain surfaces and switch to background mode when a static or
animated scene is selected. Preserve original scene brightness and colors,
using text shadows and local control surfaces for readability.
Retain bundled Vellum typography and original scene
artwork. Verification and the full-suite/live-app limits are documented above.

## Scoped publication validation

The publication branch was isolated from current main at `bcd72b1`; unrelated
local identity, voice, streaming, and workspace changes were excluded. The
109 focused frontend checks, 85 backend settings checks, and production desktop
build pass in that isolated checkout using the existing installed dependencies.
Action Parity validates the reviewed new theme control. The earlier development
results and desktop bundle hashes above describe the original local checkout.
Screenshots and pixel results are development rendering evidence, not a live
walkthrough of the isolated branch. Servers remain untouched.
