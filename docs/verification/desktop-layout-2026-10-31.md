# Desktop layout and page history, 2026-10-31

The user reported desktop-only layout defects and requested page-history arrows in the application title bar. The web layout is the reference; these changes are scoped to Electron.

## Changes and ownership

- The desktop frame no longer applies a full-window backdrop filter. That filter made the fixed Settings page relative to an already-offset ancestor and doubled the 38px title-bar offset. Settings and its navigation now have opaque theme-derived surfaces.
- Desktop main panels lose their 8px inset, outer border and corner radius. Browser-mode sidebar allocation and its child both use 208px. The closed-sidebar toolbar has its own title clearance. These overrides do not change web layout rules.
- The desktop Plugins directory uses the full workspace while the existing browser session stays alive. Opening Browser from that directory returns to Chat. Browser operations and session ownership are unchanged.
- Desktop chrome uses one title-bar height and aligned system-font menu controls. Computed CSS colors, including color(srgb) values, are normalized for the native caption-button overlay.
- Covered background rendering receives the existing paused property while desktop Settings is open. Unused desktop pointer-glow writes and redundant blurred decorative layers are skipped; individual Appearance hover previews remain independent. No new animation/runtime owner is introduced.
- The application owns a bounded 100-entry, in-memory page-location journal. Back/Forward restore chats, page views and Settings sections; forward entries are discarded when the user takes a new path. It stores identifiers and presentation locations, never message content. It is discarded on reload. Chat restoration uses conversation.open and Settings visibility uses Workspace Layout presentation. Restoring an empty chat does not create a conversation. Unavailable-chat receipts do not advance history. Website history inside the embedded browser remains separate.
- Title-bar arrows have accessible names, disabled states and Alt+Left/Right shortcuts when the Vellum workspace has focus. Native guest web contents retains its own keyboard handling.

## Verification actually performed

The user authorized isolated headless checks with fake data only. No signed-in browser, real chats or desktop UI were automated.

1. A temporary Playwright/Brave fixture loaded the real compiled CSS in production order with fake DOM. Before the fix it failed on nine assertions matching the screenshots: Settings y=76 rather than 38, translucent Settings, 8px chat insets and borders, a 52px empty sidebar reservation, closed-sidebar title overlap and a 104px Plugins content column.
2. After the fix, 15 cases passed at 960, 1280 and 1600 CSS pixels: Settings, browser split with sidebar open/closed, Plugins and the unchanged web reference. Assertions cover Settings placement/opacity, native main margin/border/radius, sidebar allocation, title clearance, Plugins width and horizontal overflow. Screenshots were reviewed from the fake-data fixture; they are not captures of the user's application.
3. The real desktop chrome and extracted production React history block passed isolated fake-state checks for empty-chat bounds, multiple chats, Music, Settings section traversal, back/forward branching, canonical-action adapter calls, unavailable conversation handling and F10 menu focus. Playwright wait-for-function polling stalled despite successful direct state reads; the fixture uses bounded explicit state polling instead.
4. desktop/scripts/build-ui.cjs passed and refreshed desktop/resources/ui. Existing Vite warnings remain for copied classic scripts, bundle size, and an orphan CSS rule in plugin-workspace.css. These are not newly introduced build failures.
5. Reviewed and registered all five imperative desktop-chrome handlers in Action Parity. Updated only the current entry's reviewed pointer handler fingerprint and the new native-chrome fingerprint. Full inventory validation still reports seven pre-existing working-tree issues: query-string source resolution for two components, two unrelated component fingerprint mismatches, and a sidebar source-probe mismatch. These were not suppressed or broadly refreshed.
6. Impeccable detection found four existing entry-page warnings (gradient text, observation/voice pulse indicators and a glow). This patch preserves the user's existing theme and live indicators. No detector findings were reported in desktop-chrome.css or desktop-chrome.js. Impeccable reported an available update during setup; no tool update was installed.

Fixture scripts, measurements and fake screenshots remain under .scratch/desktop-layout. No full test suite, provider flow, real Electron interaction, packaged install or frame-rate benchmark was run. Existing desktop sessions need a normal workspace reload (Ctrl+R) to load the rebuilt static UI. No restart of the backend is required by these UI changes.
