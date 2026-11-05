# Sidebar and Library verification — 2026-11-02

This is a narrow extension of the existing Vellum shell and Library. It preserves the incumbent [DESIGN.md](../../design/Velllum/uploads/DESIGN.md) and design token sidecar unchanged. It reuses the current surface/text tokens, shared icons, sidebar rows, and feature layouts; it does not establish a new visual identity or claim a complete audit against every rule in the design document.

## Implementation

- The destination rail opens Home, Library, Music, and Customize. Home and Library receive contextual sidebars; Music and Customize retain their own sidebars. One contextual sidebar toggle appears in the desktop titlebar or web rail. The Vellum/Coding menu presents Coding as disabled with “Coming soon.”
- Conversation rows derive status and hover-card details from the existing chat data. Shared icons match the rail and contextual controls. Long-title motion measures overflow, uses 70 px/s with a 2.4 s cap, and falls back to static titles for reduced motion.
- Library exposes projects as folders, Favorites, Trash, source filtering, sorting, search, grid/list layouts, selection, and previews. Chat attachments are a read-only projection of existing conversations. Uploads and organization use the existing session collection; the sidebar discloses that they reset on reload. This adds no persistent file manager or cloud sync.
- Notifications render in an opaque portal anchored to the bell and are hidden while Settings is open. Legacy duplicate feature buttons and the outer frame were removed.

The production entry is [Vellum Default Re-designed.html](../../design/Velllum/uploads/Vellum%20Default%20Re-designed.html). The affected components are `navigation-shell.jsx/.css`, `desktop-chrome.js/.css`, `browser-panel.jsx`, `music-page.jsx`, and `automation-notifications.jsx/.css` under `design/Velllum/uploads/components/`.

## Source and component evidence

The disposable preview rendered the real components and CSS with fake data in muted, headless Brave, with network access blocked. It used no accounts or private data. These artifacts are local source/component evidence, not proof of an attended production desktop session.

[Measurements](../../.scratch/navigation-preview/measurements.json) record:

| Check | Observed result |
| --- | --- |
| Visible web sidebar toggles | 1 |
| Mode-menu surface | Opaque `color(srgb 0.105882 0.0941176 0.0980392)` |
| Long-title transition | 2.4 s |
| Notification anchor | Panel bottom 861 px; bell bottom 861 px |
| Narrow Library layout | Main region x = 48 px, width = 592 px; no overflow |
| 320 px Library list | Client width = scroll width = 236 px |
| Preview page errors | None recorded |

Screenshots: [sidebar](../../.scratch/navigation-preview/sidebar.png), [mode menu](../../.scratch/navigation-preview/mode.png), [notifications](../../.scratch/navigation-preview/notifications.png), [Library grid](../../.scratch/navigation-preview/library-grid.png), [Library list](../../.scratch/navigation-preview/library-list.png), [narrow Library](../../.scratch/navigation-preview/library-narrow.png), [narrow Library with sidebar open](../../.scratch/navigation-preview/library-narrow-open.png), and [320 px Library](../../.scratch/navigation-preview/library-320.png).

The mechanical detector returned `[]` before the correction pass and was not rerun afterward. The independent reviewer marked three named fixes resolved: mobile surface opacity, narrow list layout, and project keyboard access. Source syntax was parsed successfully.

## Verification limits

No backend tests or full suites were run for this work. The desktop UI build completed successfully through `desktop/scripts/build-ui.cjs`, and the generated bundle contains the new shell components. There is no attended live desktop/native-chrome verification or complete Music/Plugins flow proof. The component preview does not prove account integrations, persistent file organization, or behavior after an application reload.

The desktop change updates the compiled local UI resources. An already open renderer must use View → Reload (Ctrl+R), or reopen Vellum, to load the new bundle; the app is not forcibly restarted. A pre-existing orphan CSS declaration in the Plugins stylesheet was removed after the first build reported it.

The local Electron UI server at `127.0.0.1:5184` served `/assets/Vellum Default Re-designed-C4GSztMm.js`. Its JavaScript bytes matched the rebuilt resource bundle and contained the shared shell; its served desktop chrome script contained `vellum:sidebar-toggle`. This checks delivery, not an attended native-window interaction. The final build retained Vite warnings for existing classic scripts and bundle size; the orphan Plugins CSS declaration warning was cleared.

### Conversation hover actions

Pin/Unpin and Archive buttons now share the reserved action area with Options. They appear on hover or keyboard focus and remain visible for touch input. They reuse `chatMenuAction` and its canonical `conversation.pin`, `conversation.unpin` and `conversation.archive` dispatches, with pending controls disabled. The isolated mock recorded `c0/pin` and `c0/archive` with no chat-open callback and no page errors; it did not mutate real conversations.
