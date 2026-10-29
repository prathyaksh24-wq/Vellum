# Browser use design verification — 2026-10-04

**Disposition: ship.** This is an ordinary extension of Vellum's incumbent
interface. The approved direction is a spacious sidebar/chat/browser split
with a dedicated Brave preview; the main agent delegates browser work to
`BrowserAgent`, and **More** exposes the remaining navigation destinations.
Behavior and privacy boundaries are documented in [Browser use](../browser-use.md).

## Visual authority and scope

The user's original Vellum screenshot establishes the existing identity:
dark galaxy background, Lexend body text, Clash Grotesk display text with its
existing fallbacks, muted rose accents, translucent surfaces and the Boba pet.
The approved composition changes layout within that identity. It does not
authorize a replacement visual system.

The implementation keeps a 208px sidebar and separate rounded chat/browser
surfaces on desktop. Browser controls reuse the incumbent color variables,
typography and focus treatment. The companion is placed outside the controlled
browser surface on desktop and hidden while browsing at narrow widths. At
900px and below, the browser becomes an inset overlay; the preview preserves
the browser viewport's aspect ratio with letterboxing.

Sources reviewed:

- Incumbent screenshot: `vellum-current-reference.png`, supplied for this task.
- Approved composition: `exec-4c891169-c8b3-4a02-a1a7-b3da7fc9cbfb.png`.
- Served entry: `design/Velllum/uploads/Vellum Default Re-designed.html`.
- Browser component: `design/Velllum/uploads/components/browser-panel.jsx`
  and `browser-panel.css`.

## Evidence and review resolution

The final captures, produced on 2026-10-03, were inspected at the requested
desktop size, a second desktop size and a narrow mobile size:

| Capture | Viewport | Result |
| --- | --- | --- |
| `user-1536.png` | 1536 × 1024 | Sidebar/chat/browser hierarchy and incumbent identity retained. |
| `desktop.png` | 1440 × 1000 | Split remains spacious; browser controls, composer and footer remain visible. |
| `mobile.png` | 390 × 844 | Inset browser overlay fits; tabs and address truncate; controls and close-session action remain visible. |

Generated captures and reports are local QA artifacts under
`.impeccable/review/` and are excluded from the Git diff.

The live UI smoke (`browser-smoke.json`) reports a pass
for real separate Brave launch, More disclosure, scaled manual click and
keyboard input, pause/resume, tabs, download saving, close/reopen,
desktop/mobile overflow and absence of page errors. Its page and conversation
content are synthetic localhost fixtures, not evidence of production-site
compatibility. This documentation pass inspected the saved results rather than
rerunning the smoke.

The detector report (`detector.json`) contains no
findings (`[]`). The composition diff (`diff-result.json`)
scores overall similarity at **0.4828** and labels the result **contradicted**.
That automated comparison is retained as evidence, not reported as a visual
pass: the approved comp shows a Project Gutenberg example and illustrative
conversation, while the rendered implementation shows a synthetic live page,
actual controls and the preserved incumbent galaxy/pet treatment. The finish
review accepted the desktop as an incumbent-preserving adaptation of the
approved composition.

The finish review's remaining mobile finding was a stray shared-layout hover
pill above the browser overlay. The scoped mobile rule now hides
`.shared-layout-pill` only while the browser is active at widths of 900px and
below. The final mobile capture was refreshed after this fix; the finish
disposition is **ship**.

## Existing documentation drift and remaining gates

`PRODUCT.md` was already missing when context was established.
`design/Velllum/uploads/DESIGN.md` describes a different visual direction,
including a no-mascot rule that conflicts with the incumbent screenshot.
This is pre-existing drift. No visual-system refresh was authorized, so
`DESIGN.md` was preserved and no `.impeccable/design.json` was generated or
rewritten. This report records the surface-specific decisions without creating
new system tokens.

Real sign-in, CAPTCHA, DRM and sites that reject automation remain human or
live-site compatibility gates. Only installed Brave was exercised; configurable
Chromium overrides do not have equivalent validation. See the separate
[behavior verification](browser-use.md) for backend results and known limits.
