**Comparison Target**

- Source visual truth: `C:\Users\User\OneDrive\Pictures\blue.png`, `C:\Users\User\OneDrive\Pictures\colo.png`, and `C:\Users\User\OneDrive\Pictures\landing.png`.
- Browser-rendered implementation: `C:\Users\User\.codex\visualizations\2026\06\29\019f1202-f6b9-7481-9077-0d3442515ffb\vellum-clouds-qa-1314x669.png`, `C:\Users\User\.codex\visualizations\2026\06\29\019f1202-f6b9-7481-9077-0d3442515ffb\vellum-gold-rays-qa-1314x669.png`, and `C:\Users\User\.codex\visualizations\2026\06\29\019f1202-f6b9-7481-9077-0d3442515ffb\vellum-rocket-blast-final.png`.
- Side-by-side evidence: `C:\Users\User\.codex\visualizations\2026\06\29\019f1202-f6b9-7481-9077-0d3442515ffb\vellum-clouds-comparison.png` and `C:\Users\User\.codex\visualizations\2026\06\29\019f1202-f6b9-7481-9077-0d3442515ffb\vellum-gold-rays-comparison.png`.
- Viewport: 1314 x 669 desktop for the matched comparison captures.
- States: Drifting Clouds in light mode, Gold Rays in dark mode, Rocket Blast in dark mode, and Appearance settings with live background previews.

**Findings**

- No remaining P0, P1, or P2 visual findings in the requested scope.
- Fonts and typography: existing Lexend/Clash Grotesk hierarchy is preserved; foreground polarity now follows background luminance and remains readable over both bright clouds and the Gold Rays hotspot.
- Spacing and layout rhythm: sidebar, composer, landing copy, settings modal, cards, and navigation geometry are unchanged; only their semantic surface tokens changed.
- Colors and visual tokens: the unrelated bronze/white app-mode palette was replaced by per-background foreground, muted, surface, border, accent, glow, and shadow tokens. Bright backgrounds use dark ink and cool light glass; dark backgrounds use light ink and tinted dark glass.
- Image and animation fidelity: shader output remains unobscured by a full-screen overlay. Rocket Blast uses the published 115-frame ASCII source and renders a live frame sequence rather than an approximation or screenshot.
- Copy and content: existing Vellum product copy is preserved. Appearance helper copy now explains automatic palette matching.

**Focused Region Comparison**

- Sidebar: verified nav labels, metadata, icons, profile card, borders, and scrollbar against the background-specific token set.
- Composer: verified prompt, model picker, microphone, submit button, border, shadow, and glass tint over bright and dark shader regions.
- Landing copy: verified the Vellum wordmark and greeting over cloud highlights and the Gold Rays core.
- Appearance picker: verified live shader cards and simultaneous Rocket Blast full-background/preview rendering with no browser console exceptions.

**Comparison History**

- Initial P1: light/dark app mode independently recolored controls, producing white cloud surfaces with bronze accents and dark Gold Rays text. Fix: introduced background-owned semantic palette metadata and applied it app-wide.
- Initial P1: palette variables were applied after the first React render, allowing transitioned controls to retain the previous theme color. Fix: bootstrap the stored background palette before React mounts, then keep it synchronized on theme/background/accent changes.
- Initial P2: landing wordmark halos overwhelmed the intended foreground color on bright and high-energy shader regions. Fix: use tone-specific gradient ink with a restrained drop shadow while keeping body-copy contrast protection separate.
- Post-fix evidence: the matched cloud and Gold Rays comparison images above show consistent surface tinting and readable foregrounds without a full-screen black scrim.

**Implementation Checklist**

- [x] Add Rocket Blast to the extensible background registry.
- [x] Load and cache the original published frame set only when rendered.
- [x] Add reduced-motion behavior and responsive ASCII scaling.
- [x] Apply background-aware tokens to sidebar, composer, cards, settings, buttons, dock, preview rail, menus, and typography.
- [x] Persist background selection and initialize its palette before first render.
- [x] Verify bright, dark, and ASCII backgrounds in Chromium with zero console exceptions.

**Follow-up Polish**

- P3: Rocket Blast is fetched from its published registry at runtime to keep the standalone HTML small; an offline build can vendor/compress the same frame set later if Vellum needs to run without network access.

final result: passed

---

## Cosmic coding landing and text cascade

**Comparison Target**

- Source artwork: `C:\Users\User\OneDrive\Pictures\dreamor-Image 4.png`.
- Motion reference: BeUI Text Cascade and its ActionSwap cascade variant.
- Browser-rendered implementation: not captured because this Codex Desktop session does not expose a callable in-app-browser screenshot tool.
- Intended URL: `http://127.0.0.1:8765/design/Velllum/uploads/vellum-workspace.html`.

**Implemented State**

- The landing uses the supplied planet artwork as a responsive cover background; the checked-in WebP preserves its 2944 x 1632 dimensions while reducing transfer size to 648,234 bytes.
- The headline cycles through “Build what's next.”, “Plan with every agent.”, and “Ship from one place.”
- Incoming letters rise by 105% with a 25 ms left-to-right stagger. Outgoing letters move upward with the shorter 12.5 ms stagger used by the BeUI cascade design.
- The supporting copy and composer placeholder are shorter. Existing provider selection, access controls, and message sending remain wired to the same workspace state.
- Reduced-motion users get instantaneous text changes without blur or transforms.

**Automated Checks**

- [x] Inline JSX parses with the workspace Babel parser.
- [x] `backend/tests/test_coding_workspace_html.py`: 3 passed.
- [x] `frontend/ui/coding-api.test.js`: 10 passed.
- [x] The local HTTP server returns 200 for the HTML and background asset.
- [x] `git diff --check` reports no patch errors.

**Visual QA Needed**

- [ ] Capture the landing at 1440 x 900 in the user's in-app browser.
- [ ] Compare the rendered crop against the supplied artwork at the same viewport.
- [ ] Verify heading contrast over the pink rim, composer separation, mobile crop, and all three cascade transitions.

final result: blocked

---

## Pulse composer, streaming orbs, and full-workspace cosmic background

**Source Evidence**

- Border Beam pulse reference: `https://beam.jakubantalik.com/pulse`.
- Border Beam source: `https://github.com/Jakubantalik/border-beam`, version 1.3.0 at commit `50ebc2405fca40d0b907ec4c721a3cf4b1f96e25`.
- Thinking Orbs reference: `https://orbs.jakubantalik.com/`.
- Thinking Orbs source: `https://github.com/Jakubantalik/thinking-orbs`, version 0.1.1 at commit `eda2d708b99ab871993bbea5a5f08d23a14da436`.
- Both packages are MIT licensed. Their license and source details are retained in `design/Velllum/uploads/vendor/LICENSE.jakubantalik-components`.
- Static source visuals inspected: the Border Beam demo's `og-v2.jpg` and `pulse-bg.png`, plus the Thinking Orbs demo's `header.png`.

**Implemented State**

- Every coding composer uses the source `pulse-inner` beam. Idle strength is 0.48 over 2.8 seconds; active streaming strength is 0.92 over 1.65 seconds.
- The source Thinking Orb canvas is connected to provider events rather than a demo timer: turn start maps to solving, assistant deltas to composing, file changes to shaping, commands to working, search-like tools to searching, and questions or permissions to listening.
- The supplied cosmic image now belongs to the workspace root. Chat, sidebar, drawers, files, terminal, memory, and settings use translucent surfaces so the same image remains visible across states.
- The bundled components use the page's existing React 18 global and add no network request or new runtime package to the standalone HTML.
- Both components retain their source reduced-motion behavior. The orb also pauses when offscreen or when the tab is hidden.

**Automated Checks**

- [x] Inline JSX and the component contract parse successfully.
- [x] The vendored bundle exports `BorderBeam` and `ThinkingOrb`.
- [x] A jsdom React smoke render produced both the pulse bloom layer and orb canvas.
- [x] `backend/tests/test_coding_workspace_html.py`: 3 passed.
- [x] `frontend/ui/coding-api.test.js`: 10 passed.
- [x] The page, motion bundle, and cosmic background return HTTP 200 from the local preview.
- [x] `git diff --check` reports no patch errors.

**Visual QA Needed**

- [ ] Capture the landing, active streaming chat, and settings state at 1440 x 900 in the user's in-app browser.
- [ ] Compare the pulse boundary, 20 px orb clarity, cosmic image visibility, text contrast, and side-panel glass against the source references.
- [ ] Verify the 390 x 844 crop and reduced-motion state.

final result: blocked

---

## Workspace chat navigation and live Codex connection

**Validation Target**

- Browser-rendered implementation: `D:\Vellum-worktrees\local-first-coding-platform\.api-runtime\workspace-latest.png`, `workspace-runtime-menu.png`, `workspace-real-chat.png`, and `workspace-general-chat.png`.
- Viewport: 1440 x 1000 Chromium.
- States: landing, runtime dropdown, project chat after a live Codex turn, sidebar hidden, edge-hover reveal, and top-level general chat after a live Codex turn.

**Findings**

- The runtime dropdown contains only Codex, Claude Code, and Grok state labels; the descriptive subheadings are absent.
- Both project-scoped and top-level general chats reached the real `/api/coding` session and streaming-turn path. The observed final responses were `VELLUM_UI_CONNECTED` and `VELLUM_GENERAL_CHAT_CONNECTED`.
- Active chats expose an explicit back control. The sidebar can be hidden from its header, restored from the left-edge hover target, or toggled with the existing keyboard shortcut.
- The Progress toggle is absent from the rendered active-chat interface.
- Vellum's Codex adapter keeps per-session SQLite state separate from the Codex desktop app and supports an explicit Vellum model override without replacing the user's shared Codex authentication/configuration.

**Implementation Checklist**

- [x] Keep real message sending available inside a project and from a top-level general chat.
- [x] Default an unselected project root to the API process workspace instead of blocking send.
- [x] Add explicit sidebar hide, edge-hover reveal, and active-chat back controls.
- [x] Remove runtime descriptions and the Progress toggle.
- [x] Verify both chat scopes with real streamed Codex responses in Chromium.

**Environment Note**

- The C: system volume had no free space during validation, and the installed CLI was older than the model selected in the desktop Codex config. The live preview therefore uses `VELLUM_CODEX_SQLITE_HOME` on D: and an explicit compatible `VELLUM_CODEX_MODEL`; these remain deployment configuration rather than hard-coded user credentials.

final result: passed

---

## Workspace sidebar and SideRays shell

**Comparison Target**

- Source visual truth: `C:\Users\User\OneDrive\Pictures\codex dropdown.png`, `C:\Users\User\OneDrive\Pictures\codex sidebar.png`, and `C:\Users\User\OneDrive\Pictures\sidebar projects.png`.
- Browser-rendered implementation: `D:\Vellum-worktrees\vellum-workspace-sidebar-rays.png`, `D:\Vellum-worktrees\vellum-workspace-runtime-2.png`, `D:\Vellum-worktrees\vellum-workspace-project-2.png`, and `D:\Vellum-worktrees\vellum-workspace-send-2.png`.
- Side-by-side evidence: `D:\Vellum-worktrees\compare-runtime-dropdown.png` and `D:\Vellum-worktrees\compare-project-sidebar.png`.
- Viewport: 1440 x 900 desktop; focused sidebar comparisons use a 503 x 736 crop matching the supplied project-sidebar reference.
- States: landing idle, runtime menu open, project-add menu open, and active project chat after send.

**Findings**

- No remaining P0, P1, or P2 visual findings in the requested frontend scope.
- Fonts and typography: Karla is now the workspace body/UI family, Fraunces is the heading family, and monospace remains limited to code/runtime metadata where semantic scanning benefits from it.
- Spacing and layout rhythm: the 266 px persistent sidebar, grouped navigation, section labels, nested project chat rows, runtime menu, bottom profile row, and project-add popover follow the density and hierarchy of the supplied Codex references.
- Colors and visual tokens: the sidebar adopts the reference's near-black and green palette. The chat surface remains darker and quieter so the requested gold/blue procedural rays are visible without reducing text or composer contrast.
- Image and animation fidelity: SideRays is implemented as a responsive canvas background using the supplied speed, colors, intensity, spread, origin, tilt, saturation, blend, falloff, and opacity. It renders behind both landing and active-chat states and honors reduced-motion preferences.
- Copy and content: Sites is intentionally omitted. Codex and Claude Code are selectable runtimes; Grok appears in the dropdown with an explicit not-connected state instead of implying a backend integration that is not present.

**Focused Region Comparison**

- Runtime selector: the combined comparison verifies the rounded selector, search action, stacked runtime names/descriptions, selected state, and disabled Grok state at readable scale.
- Project sidebar: the combined comparison verifies the persistent left rail, project hierarchy, nested active chat, section actions, profile row, and omission of Sites.
- Active chat: the post-send capture verifies that the removed provider/project strip does not return after a message and that SideRays remains mounted behind the conversation and composer.

**Comparison History**

- Initial P1: the workspace exposed a separate global utility bar and a provider/project strip above both composer states, conflicting with the supplied single-sidebar information architecture. Fix: removed both surfaces and moved runtime selection into the sidebar dropdown while keeping access selection in the working composer.
- Initial P1: projects were absent from the rendered sidebar even though project state and handlers existed. Fix: restored a visible Vellum project tree with nested chats, add-folder/start-new actions, and project menus using the existing frontend state.
- Initial P2: the prior neutral sidebar lacked the green-on-black hierarchy and persistent desktop width shown in the reference. Fix: introduced scoped workspace sidebar tokens and made the web shell open it by default.
- Post-fix evidence: the runtime, project-menu, and post-send browser captures above show the corrected states with no remaining actionable mismatch.

**Implementation Checklist**

- [x] Apply Fraunces/Karla across the standalone coding workspace.
- [x] Remove the global Vellum Workspace utility bar.
- [x] Remove the provider/project strip from landing and active chat.
- [x] Add the procedural SideRays background to both chat states.
- [x] Add the Codex/Claude Code/Grok runtime dropdown and honest capability state.
- [x] Restore project, nested-chat, pinned, general-chat, add-project, and profile sidebar regions without adding Sites.
- [x] Verify landing, open-menu, project-add, and post-send states in Chromium and compare focused regions against the supplied references.

**Follow-up Polish**

- P3: Pull requests, Scheduled, and the top-level Plugins entry are intentionally non-operational in this frontend-only pass and are visually muted with explanatory titles until their product flows are connected.

final result: passed

---

## Studio coding composer

**Comparison Target**

- Source visual truth: `C:\Users\User\AppData\Local\Temp\beui-agent-chat-input-preview-11ty.png` captured from `https://pro.beui.dev/preview/agent-chat-input`.
- Browser-rendered implementation: `D:\Vellum-worktrees\vellum-workspace-studio-final.png`.
- Side-by-side evidence: `D:\Vellum-worktrees\studio-composer-comparison-final.png`.
- Viewport: 1440 x 900 desktop; the intended Vellum coding-workspace surface.
- State: dark theme, landing composer idle, Codex selected, read-only access, provider backend unavailable in this static-browser capture.

**Findings**

- No remaining P0, P1, or P2 differences in the requested composer scope.
- Fonts and typography: the composer now inherits the requested Karla body family while retaining Geist Mono only for runtime metadata; the prompt remains 15.5 px with the reference's quieter placeholder and compact toolbar labels.
- Spacing and layout rhythm: the composer now uses the reference's wide, low profile, 21 px radius, inset toolbar, grouped left/right controls, and layered queue rail when follow-ups exist.
- Colors and visual tokens: Vellum's neutral near-black surfaces and orange status accent are preserved instead of importing BeUI's product palette.
- Image and asset fidelity: the composer has no raster artwork or custom visual asset requirement; it reuses Vellum's established icon set and does not introduce placeholders.
- Copy and content: source labels are adapted to real Vellum capabilities: Coding agent, selected provider SDK, access mode, attachments, dictation, send/stop, and queued follow-ups.

**Focused Region Comparison**

- The source and implementation composer regions were cropped to comparable scale in the side-by-side evidence above. The controls, input hierarchy, corner geometry, and footer grouping remain clearly readable at that scale.
- A separate browser interaction harness verified the Add menu, access menu, runtime menu, controlled text input, enabled send state, and dictation capability. Evidence: `D:\Vellum-worktrees\studio-composer-interaction-qa-3.png`.

**Comparison History**

- Initial P2: Vellum's landing composer was 620 px wide, making its control groups visibly more cramped than the source. Fix: widened the landing slot to 760 px while retaining the existing responsive collapse rules.
- Post-fix evidence: `D:\Vellum-worktrees\studio-composer-comparison-final.png` shows the corrected proportions with no remaining actionable composer mismatch.

**Implementation Checklist**

- [x] Preserve the existing coding-session, provider, access, stop, and event-stream wiring.
- [x] Add a functional provider switcher and permission selector inside the composer.
- [x] Add text-file ingestion, image/file chips, browser dictation, and send/stop states.
- [x] Queue follow-up prompts while a provider is running, with steer, edit, remove, and explicit run actions.
- [x] Parse the inline JSX, run the workspace regression tests, render in Chromium, and exercise the primary composer controls.

**Follow-up Polish**

- P3: the surrounding Vellum workspace remains intentionally desktop-first below tablet width; the composer itself collapses cleanly, but a future mobile workspace project would need broader shell changes.

final result: passed

---

## Current visual QA status

- The latest change is the “Pulse composer, streaming orbs, and full-workspace cosmic background” section above.
- Its component bundle, parse, focused tests, asset requests, and patch checks passed.
- A matched in-app-browser screenshot comparison of the landing, active streaming chat, settings, mobile crop, and reduced-motion state is still required before visual sign-off.

final result: blocked
