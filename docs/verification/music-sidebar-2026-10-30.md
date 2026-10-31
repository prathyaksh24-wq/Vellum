# Music sidebar and background — 2026-10-30

## Changes

- Retained Music's canonical component, SpotifyPlayer snapshot, Local Music hook and App Actions. Playback transport, imports, playlist writes and connection behavior are unchanged.
- Replaced the single scrolling sidebar with an anchored Music header and collapse control, full-width provider picker, Home/Search/Playlists navigation, a separately scrolling playlist collection with artwork, and Sources/Settings at the bottom. Local mode retains Add music in place of Sources.
- Preserved existing collection IDs and selection callbacks. Active rows and pointer/focus movement use the shared local background component. Navigation does not create a new router or saved state.
- Removed the separate dark Music canvas and inset content background. Desktop sidebar/player surfaces use a lighter blend of Vellum's existing surface, allowing the selected background to show through. Mobile off-canvas navigation uses an opaque themed surface for readability.
- Reused VSelect with real Spotify/Apple assets and a local music icon, a menu matching the chooser width, and shared row motion. Apple Music remains explicitly marked Coming later. Removed the fixed 214px menu width and the separately positioned provider logo.
- The old provider logo had z-index 601 outside a local stacking context. Music now isolates its stacking context and the logo is part of the selector's normal layout. It no longer paints above the main sidebar's hover panel.

## Inspection

No test suites or production builds were run, following the user's instruction.

- Parsed the changed Music JSX with Babel. Main inline JSX syntax also parsed successfully after asset-version changes.
- Scoped `git diff --check` passed after removing an extra trailing blank line in Music CSS.
- Inspected the running local UI in isolated Edge at 1440×1000 and 390×844. The real read-only library projection populated 17 Spotify playlists during inspection. No playback, import, collection edit or provider-connection operation was performed.
- Music workspace and inset content both computed `rgba(0,0,0,0)` backgrounds. The desktop sidebar/player used the active surface at approximately 0.34 alpha; the mobile drawer used the same hue at full opacity.
- The desktop provider menu was 232px wide and remained within the 260px sidebar. Its three options displayed Spotify, Apple Music with Coming later, and Local files. Pointer movement moved the single shared row background. The selected option's former static fill was cleared so it does not compete with the moving highlight.
- Playlist scrolling left the header in the same position. Music sidebar hide/show completed. The mobile provider menu stayed within the 390px viewport, and document scroll width remained 390px.
- Briefly unpinned the main sidebar, revealed its actual hover panel, and inspected the provider logo's center using `elementFromPoint`: the topmost element belonged to the main sidebar. Restored the original pinned state afterward.
- No page errors occurred in either inspection pass. These observations do not establish audio playback, subscription authorization or provider reliability.

## Action Parity

Compared changed Music handlers with a task-start snapshot. The previous source matched its locked inventory: 106 handlers. The new component has 107 because navigation is split into two groups. Both groups still call the existing `navigate(id)`, and playlist rows retain the existing Local/Spotify collection callbacks. Updated only the reviewed Music fingerprint. CSS, menu disclosure and hover changes introduce no new persisted actions. The full Action Parity suite was not run, and unrelated existing inventory drift was not refreshed.

## Proposed draft PR

**Title:** Clean up Music navigation, background layering and provider selection

**Description:** Reorganize Music's sidebar around anchored navigation, a scrolling playlist library and bottom utility actions. Reuse the shared provider selector with logos and moving row highlights, remove the separate dark canvas, and contain Music's stacking so provider logos cannot overlap the main sidebar's hover panel. JSX parsing, scoped whitespace checks and desktop/mobile browser inspections passed. Tests/builds and audio playback verification were not run.

Changes remain local. No branch, commit, push or PR was created for this task.
