# Vellum face and color preview

The supplied `Vellum face preview.html` provides the cloud geometry, motion and
blue desktop PNG. Vellum now uses the supplied Glow Blue identity by default.
The face shares the host React runtime and uses unique SVG references.

Appearance settings include a color well, validated six-digit hex input,
live app/face/icon-tile preview, Reset to blue, and Apply color. Preview edits
stay transient until Apply dispatches `settings.device.update`. The existing
revisioned device-settings owner persists `face_color` and restores it after
reload. Failed writes keep the draft available for retry. This preference is
independent of the existing app accent and background palette.

The landing face was reduced from 112px to 56px following user feedback. Its
opacity is .72, saturation .65, halo and shadow are removed, and its rim uses
the active text palette. The existing wordmark and background remain in place.
Navigation marks stay static. The larger interactive preview retains floating,
pointer tracking, blinks, squish and wink, with keyboard support. Reduced-motion,
off-screen and document-visibility controls stop animation work.

The original blue PNG is also the favicon and source of the multi-size Windows
ICO. Desktop windows and release packaging use that ICO. The installed OS icon
does not change dynamically when a face-color preference changes; Settings says
this explicitly. Its colored tile is a preview rendered with the same face.

## Verification

- Backend settings suite: 56 passed, including normalized custom colors and
  rejected invalid values with no device patch.
- Focused face/settings-runtime/project frontend suites: 34 passed. Coverage
  includes draft versus Apply, invalid input, failure/retry/reset, remount without
  saving, unique SVG IDs, reduced motion, hidden-document cleanup, and persisted
  settings reload.
- Desktop chrome/policy suites: 8 passed.
- Desktop UI build: passed and copied to `desktop/resources/ui`. It includes the
  smaller landing face and supplied icon. Existing large-chunk warnings remain.
- Design detector over the new face component/styles: no findings.
- Browser: the real Appearance page and color controls rendered at the supported
  local origin. The final smaller landing face was built after that inspection;
  native desktop visual validation and a live Apply/reload were not completed.
- Full frontend run: 542 passed, 49 failed, with 8 worker errors. Failures include
  missing fixture dependencies, file-URL handling and permission errors.
  The new served component was then registered in the parity scanner with its
  Apply action and transient-preview/animation exemptions. The old inline HTML
  handler inventory remains stale: it records 995 handlers while the current
  source has 986, both with and without this task's added FaceSettings control.
  Its unrelated fingerprint was preserved. The follow-up frontend parity check still has those two inline-fingerprint failures. Backend visual parity has 2 passing checks and one existing plugin-composition failure (duplicate asana.connection.configure).

No branch, commit, push or PR was created. Existing unrelated working changes
were preserved. Only temporary Vite preview servers started for this task were
stopped to free the desktop UI port; the existing backend was left running.

## Proposed PR

Title: Add the Vellum cloud face and custom color previews

Description: Integrate the supplied cloud identity and blue desktop icon, with
a smaller background-blended landing face. Add an Appearance color picker and
live app/icon preview backed by the existing revisioned device-settings action.
Preserve unsaved drafts, expose failed saves, restore saved colors on reload,
and respect reduced motion and hidden/off-screen presentation. Installed desktop
icons retain the supplied blue build asset. Focused checks and the desktop build
pass; full-suite and native visual gaps are listed above.


## Cloud-only icon and landing spacing follow-up

The icon is now exported from the canonical VellumFace SVG geometry, with a tight `25 25 190 190` view box, no sky tile and no ground shadow. The 512px PNG has true RGBA transparency; all four corners have alpha zero and the solid cloud spans 443px (86.5% of its width). The Windows ICO includes 16, 24, 32, 48, 64, 128 and 256px sizes. `desktop/assets/icon.svg` retains the editable vector source. Favicon and Appearance icon preview now use the same cloud-only treatment. This supersedes the earlier tiled desktop-asset description.

The 56px landing face and wordmark now share a horizontal `landing-identity` row. The cloud sits immediately left of the name, vertically centered, with a 4px layout gap. The page's spacing between greeting and composer is unchanged. The running app and all servers were left untouched. Windows may retain the old taskbar icon until the app is next opened normally.

Follow-up checks: all 7 face UI tests passed; desktop UI build and copy succeeded.
