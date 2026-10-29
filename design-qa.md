# Browser homepage design QA — 2026-10-07

Scope: the five approved browser homepages, compact browser chrome and workspace
expansion. The existing Vellum shell remains authoritative outside this surface.
Whole-app themes are deferred.

## Source and capture evidence

Exact visual authority is recorded in [the scoped brief](docs/design/browser-home-approved.md).
Source root: `C:/Users/Pratyakksh/.codex/generated_images/01a1005b-83df-71b0-8e0c-d246d11c1fd5/`.
Capture root: `.impeccable/review/`.

| Engine | Source file | Final capture | State |
| --- | --- | --- | --- |
| Google | exec-77b8d88d-c001-4270-b020-75948618f1f0.png | google.png | Homepage, picker closed |
| Brave | exec-8d12a0ad-a3c5-4f52-bad6-07ed44622ef6.png | brave.png | Homepage, picker closed |
| DuckDuckGo | exec-f73c0522-9d2e-452c-be1f-3bd587421761.png | duckduckgo.png | Homepage, picker closed |
| Startpage | exec-582afc4f-2840-493b-bb46-39f8a82c8de9.png | startpage.png | Homepage, picker closed |
| SearXNG | exec-c8decf01-6671-492d-b917-5da19870470e.png | searxng.png | Homepage, picker open |

All sources and engine captures are 1586 × 992 pixels at the same CSS viewport,
device scale factor 1, without density resampling. Each source and final capture
was opened together in a single comparison tool input. Full-view comparisons
show clearly readable title, search, shortcuts, borders and menu; separate detail
crops are unnecessary at this size. Synthetic chat and restored live tabs differ
from the mock. They are functional fixture content, not homepage copy targets.

Additional captures: `expanded.png` at 1586 × 992, `user-1920.png` at 1920 × 1200,
and `mobile.png` at 390 × 844. There is no approved narrow-screen mock; mobile is
a usability adaptation. Final mobile panel bounds are x12, y12, width366,
height820. Homepage client/scroll widths are both364, so controls remain contained.
After responsive verification the incumbent sidebar is collapsed in the final
engine captures. This is the existing shell's responsive state; engine page areas
are918 ×861 and homepage fidelity remains the scoped comparison target.

## Findings and correction evidence

The first independent review requested one batch of corrections:

| Priority | Finding | Resolution in final captures |
| --- | --- | --- |
| P1 | Approved authority and fidelity boundary were not persisted | Scoped brief records all five references, ownership and deferred global themes |
| P1 | Startpage downloaded icon was invalid | Valid standard SimpleIcons SVG renders in title, menu and address bar |
| P1 | SearXNG menu covered search and shortcuts | Wide menu sits to the right of the title, above the search field |
| P2 | Google and DuckDuckGo controls used the wrong light palette | Blue and cyan fields/buttons now match the approved direction |
| P2 | Shortcut borders, shadows and title/picker scale drifted | Diagonal folded corners, no offset shadows, larger marks and picker |
| P2 | Narrow Add shortcut label lacked contrast | Filled quiet control remains legible over cursor wallpaper |

An initial post-fix capture set was invalid: Playwright scrolled an overflow-hidden
app ancestor while reaching menu items. No acceptance was based on those images.
The capture helper now restores every homepage ancestor to the document origin;
the final complete-chrome captures above replace that set. This was an evidence
setup correction, not an additional visual-polish pass.

The user then supplied a first-use SearXNG screenshot exposing a separate P1:
the instance form lifted the title, so the upward menu was cut off. A new bounds
regression failed before the fix. Menu layout now clamps to page bounds, caps its
height with scrolling, recalculates on resize/scroll and stays above page controls.
`searxng-setup-menu-{1920,1200,390}.png` verifies all engine choices are visible;
the smoke also checks each menu button is the actual pointer hit target. The
independent reviewer returned ship for this specific issue.

The user's subsequent alignment correction is also applied: merely choosing
SearXNG leaves the same centered homepage as other engines. Setup appears only
through the instance menu action or a search attempt without an instance. Shared
84px title rows align the controls. `searxng-unconfigured.png` and the passed
`engineTitleAligned` assertion establish this state without an automatic form.

## Required fidelity surfaces

- **Fonts and typography:** incumbent Lexend remains the live UI font. Google uses
  its supplied raster wordmark; other engines use readable live titles and standard
  brand assets. Title scale, 16px search text and14px shortcuts keep the source
  hierarchy. Existing small toolbar labels truncate for real multiple tabs.
- **Spacing and layout:** two compact chrome rows; centered title/search/shortcut
  stack; home fills the page without gray letterboxing. Expansion hides chat and
  restores split view without replacing the browser component. Shortcuts wrap on
  narrow screens and the picker remains within the panel.
- **Colors and tokens:** scoped blue/cyan/slate/dusk/petrol palettes preserve each
  source's contrast and accent. Search submit is deliberately muted while empty;
  the reference's brighter arrow corresponds to an enabled state. Focus is visible.
- **Image quality:** five generated local wallpaper assets preserve the approved
  subjects and art direction. Cover cropping adapts landscape assets to the panel;
  Brave's cat and SearXNG's cursor cascade remain visible. Standard brand/Lucide
  assets render without placeholders. All seven PNG assets retain prompt/source
  metadata. CSS folded corners are functional button border geometry.
- **Copy and content:** engine names, selected search hint, and shortcuts agree
  with the source. "Search with" is explicit about the current engine. The SearXNG
  instance action makes its required configuration clear. Fixture chat, actual
  tabs and a test shortcut are excluded from image reproduction claims.

## Behavior and accessibility

Muted Brave verification exercised all five engine choices, SearXNG setup and
encoded search destination, saved shortcut navigation, streamed page click/type,
new-tab address focus, close-tab shortcut, Escape and expand/restore. Homepage
controls run locally and do not require frame polling. Menus expose radio state,
keyboard navigation and dismissal; inputs have labels and reduced-motion disables
transitions. No frontend runtime errors were recorded.

## Limits and follow-up

This passes direct scoped visual and functional QA. No measured Impeccable comp
spec, reproduction build state or comp-diff artifact exists; one-to-one comp-tool
certification is unproven. Supplied standard brand assets may differ from drawn
mock logos. Generated wallpaper cover crops are accepted scoped adaptations.
Public-site latency, CAPTCHA policies and long YouTube playback are not established
by this muted fixture run. Real websites still use the streamed dedicated Brave
surface; this build does not introduce a native embedded desktop browser.

Implementation checklist: five homepages and picker implemented; canonical local
preferences and shortcuts persisted; assets bundled; responsive states captured;
frontend/backend checks passed; independent verdicts recorded below.
The independent review's six original corrections and the reported clipping
regression received ship verdicts. The final centered state was compared directly
against the approved SearXNG reference after the user's alignment correction.

final result: passed
