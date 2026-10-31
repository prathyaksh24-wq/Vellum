# Vellum-wide interface polish — 2026-10-30

## Direction and scope

The user approved the whole-app direction: calm, exact and quietly warm, with the character of a personal library and listening desk. Real book/album artwork, source previews and meaningful data carry the detail; shared selection motion ties controls together. This is a polish of Vellum's existing identity, not a replacement theme or runtime.

The work covers the shared shell, composer, Plugins, Music, Settings/Configuration/Analytics, Browser controls, Books host chrome, Calendar, memory/knowledge views and scheduling. Existing feature routes, section order, public contracts, privacy controls and action confirmations remain connected to their owners. Third-party browser pages and provider authorization pages are not restyled.

During implementation the user explicitly retained the landing text animations and curved glowing input. These remain intentional signatures, along with selected backgrounds, supplied thinking orbs, Bookshelf visuals, real vendor logos, the pet and user-authored content. Emoji in playlist names, messages or semantic reaction payloads are content, not decoration to delete.

## The nine passes

1. **Spacing:** aligned shared sidebar rows and tabs to a 36px desktop rhythm; used larger touch rows, consistent group separation, settings row spacing and content insets. Music's playlist list remains separately scrollable. Books' surrounding toolbar and metadata spacing follows the shared rhythm without changing the supplied scene.
2. **Color:** reused Vellum's foreground/secondary/muted roles and existing accent. Raised low-contrast default muted text, removed ordinary-composer glow and kept neutral focus borders. The landing glow and animated wordmark are retained by explicit request. Background selection and rendering are untouched.
3. **Icons:** retained the established line icons and real brand assets; aligned Music's stroke weight. Replaced the application-generated attachment emoji with a file icon. Preserved actual user content and reaction values.
4. **Copy:** replaced vague General/Configuration descriptions with labels about appearance, models, navigation, memory and account controls. Music's greeting becomes “Your music.” Normal chat uses “Message Vellum”; the landing retains its animated phrases. Unavailable controls remain unavailable and keep explanatory feedback.
5. **Type:** introduced `--font-ui` using the existing Lexend family, kept the existing display and mono roles, replaced Plugins' all-monospace treatment and Music's heavy headings, and raised small metadata in the affected owners. App-owned category labels use sentence case instead of forced uppercase tracking. Code/schema presentation remains monospace.
6. **Layout:** retained Vellum's full viewport shell, inset/off-canvas navigation and section order. Reduced excessive settings content indentation. Allowed Configuration's model selector to shrink inside its row, resolving a 7px narrow-screen overflow.
7. **Details:** kept radii appropriate to controls and panels, retained circular playback transport, and removed unnecessary pill treatment from ordinary buttons/tabs/labels. Dropdown triggers keep their rounded corners when open. The landing input keeps its requested 24px curve.
8. **Visuals:** used existing artwork, logos and real library data. No image generation, hero replacement, synthetic app data or new decorative assets were introduced. The supplied scene/uploader/orb/background source files were not edited.
9. **Motion:** removed decorative hover lifts/scales and shimmering status text while retaining functional live feedback, streaming, sidebar transitions and the requested shared menu geometry. Ordinary composers have no rotating placeholder/border loop. Landing-only effects are gated to that composer; the glow pauses while hidden and for reduced motion, and text animation disables under reduced motion.

## Profile hover bug

The profile menu is a portal outside the sidebar DOM. Previously, leaving the sidebar hid navigation while the independently owned popover stayed open. A profile menu opened from a hover sidebar now records that temporary ownership. Its portal participates in the same hover region, with the existing crossing delay, and leaving both closes both. A pinned sidebar's profile menu retains ordinary dismissal behavior. The change uses existing menu/sidebar state and adds no saved state or action path.

## Verification actually performed

No test suites or production builds ran, as requested.

- Parsed the main inline JSX and changed Music/Settings Overview JSX with Babel. Parsed changed CSS with PostCSS. Scoped whitespace checks passed.
- Inspected the running local app in isolated Edge at 1440×1000 and 390×844, using the local account-status projection. Desktop captures cover landing, slash menu, model picker, General, Configuration, Analytics, Browser settings, Responses, Plugins, Music, Memory, Knowledge graph, Scheduled, Browser and Books.
- Calendar was inspected using its real component and read-only status adapter in a temporary presentation host, with an inert action callback. This is presentation evidence, not an event-write or authorization check.
- Confirmed that Plugins and Music use the interface font role, Music headings compute weight 500, and Configuration's inspected small labels compute 12px. Technical text keeps its mono role.
- Confirmed the landing input computes a 24px radius with its focused glow, animated greeting characters, changing placeholder and animated wordmark. The final mobile landing input remained within the viewport.
- Confirmed that the hover profile menu stays visible while the pointer is over its controls, then disappears when the pointer leaves both regions; the sidebar also reaches its closed state. The original recorded pin setting was restored after inspection.
- Mobile checks cover General, Configuration, Analytics, Plugins, Music and its drawer. Touch navigation computes 44px; Plugins' content width equals its scroll width. Configuration initially had 7px of overflow; after the flex correction its body client width and scroll width both measure 390px. Analytics also measured 390/390.
- Reduced-motion inspection returned `animation-name: none` for animated text and `transition-duration: 0s` for the shared tooltip. Completed inspection rounds reported no page errors.
- No chat/inference request was sent, no credential was entered, no model/provider was selected, no audio played, and no library/book/calendar mutation was performed. The browser panel was opened/closed as part of navigation. This does not verify physical touch hardware, live provider completions, playback, import flows or every account/permission state.

## Action Parity and working state

Reviewed the handler changes against a task-start snapshot. Music and Settings Overview have unchanged handler fingerprints. Main HTML goes from 933 to 939 handlers: the delta consists of forwarding profile hover callbacks and gating the landing input's focus effect. These are presentation gestures; account/settings actions retain their canonical dispatchers. A scoped hover-menu exemption records the ownership behavior.

The main inventory already differed from its lock at task start (933 actual versus 936 locked); that pre-existing drift was preserved rather than certified through a blanket fingerprint refresh. The full Action Parity suite was not run. Reconcile existing dirty-source drift before scoped publication.

Changes remain in the existing checkout. Unrelated changes were preserved. No branch, commit, push or PR was created.

## Proposed draft PR

**Title:** Polish Vellum's shared interface and fix hover-profile dismissal

**Description:** Align typography, metadata, spacing, control shapes and copy across Vellum's shared shell and workspace views while preserving the user-selected backgrounds and supplied visual components. Retain landing text animations and its curved glowing input, scope decorative input motion to the landing page, and make a hover-owned profile menu dismiss with its sidebar. Fix narrow-screen Configuration overflow. JSX/CSS parsing, scoped whitespace checks and desktop/mobile browser inspections passed; tests/builds and live provider, playback and import flows were not run. Existing main Action Parity drift still needs publication review.

## Attribution

Design review and pass structure guided by [Unslop](https://heydamir.design/unslop), created by **Damir Sokolovsky (@heydamir)** and licensed **CC BY 4.0**. No image prompt or story video was produced.
