# Vellum Default-Mode Shell — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build `design/Velllum/uploads/vellum-default.html` — a self-contained, offline, web-previewable desktop-app preview of Vellum's **default mode**: ChatGPT-style shell (dark + light), Vellum-branded, with sidebar (New chat / Search chats / Library / Projects / Recents), collapsed icon rail, Library page, Projects page, profile popover, and Edit-profile modal.

**Architecture:** Single HTML file, React 18 + Babel-standalone (CDN), no backend/network. One top-level `App` store (`useState` per slice) drives an in-file router (`view: chat|library|projects`). Theme = `data-theme` attribute + CSS variables, persisted to `localStorage`. Desktop chrome (stage → window → titlebar → sidebar+main) reuses the `vellum-coding.html` chrome family.

**Tech Stack:** React 18 UMD, Babel JSX, CSS variables for dual themes, `crypto.randomUUID`. Verification: esbuild compile gate (`check-default.mjs`) + manual browser run-through.

**Testing note (adapted):** single-file embedded React, no unit runner. Each task verifies with (a) `node design/Velllum/uploads/check-default.mjs` → `OK: JSX compiles`, and (b) manual browser checks where observable. Non-`OK` compile = hard failure.

---

## File map
| File | Responsibility | Action |
|------|----------------|--------|
| `design/Velllum/uploads/vellum-default.html` | The entire default-mode preview app | Create |
| `design/Velllum/uploads/check-default.mjs` | esbuild JSX compile gate for the new file | Create |

---

## Task 1: Scaffold, dual-theme CSS, chrome, compile gate
**Files:** Create `vellum-default.html`, `check-default.mjs`.
- [ ] HTML boilerplate: React 18 + ReactDOM + Babel CDN, `<div id="root">`, `<script type="text/babel" data-presets="react">`.
- [ ] CSS variables under `:root` (dark) and `[data-theme="light"]`:
      dark — `--bg:#0d0d0d --panel:#0c0c0d --line:#1c1c1e --line2:#242427 --txt:#d7d7d7 --dim:#6a6a6a --dim2:#4a4a4a --ember:#e35d2b --hover:#151516 --active:#19191b --bubble:#19191b --modal:#121214`;
      light — `--bg:#f7f5f0 --panel:#efece4 --line:#ddd8cc --line2:#cfc9bb --txt:#26241f --dim:#8a857a --dim2:#b0aa9c --ember:#d14f1f --hover:#e9e5da --active:#e2ddd0 --bubble:#e9e5da --modal:#fbf9f4`.
      All component CSS uses only these vars.
- [ ] Window chrome CSS + JSX: `.stage` backdrop, `.win`, `.titlebar` (app mark, menu, centered "vellum — preview", sun/moon theme button, window controls), `.body{display:flex}`.
- [ ] `I` icon wrapper + icons: IcPencilSq (new chat), IcSearch, IcLibrary, IcFolder, IcPanel (collapse), IcDots, IcPin, IcArchive, IcTrash, IcShare, IcPlus, IcMic, IcVoice, IcSend, IcCopy, IcThumbUp, IcThumbDown, IcRefresh, IcSun, IcMoon, IcCamera, IcGrid, IcList, IcFilter, IcChevD, IcCheck, IcNote, IcUpload, IcImage, IcPdf, IcCode, IcDiffFile, IcUserPlus, IcSettings, IcHelp, IcLogout, IcSparkle.
- [ ] `App` skeleton: theme state (`localStorage('vellum-theme')` read/write, sets `data-theme` on `document.documentElement`), titlebar, empty sidebar div, main placeholder. Render via `ReactDOM.createRoot`.
- [ ] `check-default.mjs`: copy `check-coding.mjs`, target `vellum-default.html`, message `OK: JSX compiles`.
- [ ] Verify: `node design/Velllum/uploads/check-default.mjs` → `OK: JSX compiles`. Manual: theme button flips dark/light, persists reload. Commit + push.

## Task 2: Store + sidebar (expanded + rail) + recents menu
**Files:** Modify `vellum-default.html`.
- [ ] Seed data consts: `SEED_CHATS` (5 chats echoing user's screenshots: "Self-Perception and Healing" (pinned), "Live Streaming on Vellum", "Prioritizing Vellum Development", "Usage boost feature idea", "Cult UI Components for Vellum" — each `{id,title,pinned,archived,messages:[]}`), `SEED_LIBRARY` (Task 4), `SEED_PROJECTS` (Task 5), `PROFILE` default `{displayName:'Pratyakksh', username:'pratyakksh', email:'openslides.ai@gmail.com', plan:'Private'}`.
- [ ] App state: `sidebar:'open'|'rail'`, `view`, `activeChatId`, `chats`, `library`, `projects`, `profile`, `menus` (which popover/modal is open: `null|'chatmenu:<id>'|'profile'|'editprofile'|'search'|'newlib'|'mode'`). One `closeMenus()` on backdrop click.
- [ ] `Sidebar` (expanded ~260px): header (wordmark `vellum` italic-v + IcPanel collapse btn) · nav rows New chat (resets to landing: new empty chat), Search chats (opens overlay), Library, Projects (switch view; active view highlighted) · `Recents` label · chat rows sorted pinned-first, skipping `archived`; active chat `.active`; hover reveals IcDots.
- [ ] Chat `⋯` context menu (anchored popover): Share (dim "not in this preview" hint line under it), Rename (inline input swap, Enter/blur commits), Pin/Unpin (re-sorts), Archive (hides row), Delete (red; removes chat, falls back to landing if active).
- [ ] Profile row at sidebar bottom: avatar circle (initials from displayName), name, plan, edit glyph. Click → opens profile popover (Task 6 fills it; stub now).
- [ ] `Rail` (collapsed ~52px): logo mark (expand), icon-only new chat/search/library/projects with `title` tooltips, avatar bottom. Collapse btn ↔ rail logo toggle `sidebar`.
- [ ] Verify compile + manual: collapse/expand, rename/pin/archive/delete all work. Commit + push.

## Task 3: Chat view — landing, thread, composer, streamed replies
**Files:** Modify `vellum-default.html`.
- [ ] `Composer` (shared landing/thread): rounded pill — IcPlus (attach), textarea ("ask." placeholder, autosize, Enter sends / Shift+Enter newline), mode chip `Extended ⌄` (menu: Extended/Instant, state only), IcMic (dim, no-op title "not in this preview"), ember send/voice button (IcVoice when empty, IcSend when text).
- [ ] Landing (active chat has no messages): centered wordmark, greeting `What are you reading.`, composer, three chips — `Write or edit`, `Look something up`, `From your library` — click prefills composer text.
- [ ] Thread: user bubbles right (`.bubble`), attachments as small chips on the bubble; Vellum reply = plain prose, streamed char-wise (~12ms tick) with shimmer while streaming; after done, action row: IcCopy (clipboard, brief "copied" swap), IcThumbUp/Down (toggle state), IcShare (dim no-op), IcRefresh (regenerate → re-streams variant).
- [ ] `vellumReply(text)`: keyword buckets → canned Vellum-voice replies (reading/books → library-flavored; build/code → pointer to coding preview; default → quiet reflective answer weaving the user's words). Two variants per bucket for regenerate. No exclamation marks.
- [ ] Sending in a fresh chat sets its title from the first message (truncated ~28 chars) so it appears in Recents.
- [ ] `+` attach: hidden `<input type=file>`; on pick, push `{name,kind:by extension,size,modified:'Today'}` into `library` and attach chip to the pending message.
- [ ] Verify compile + manual: send → stream; regenerate; copy; attach lands in Library state. Commit + push.

## Task 4: Search-chats overlay + Library page
**Files:** Modify `vellum-default.html`.
- [ ] `SearchOverlay`: dimmed backdrop + centered card; search input autofocus; rows: `New chat` first, then chats filtered by title (case-insensitive live); click/Enter opens; Esc/backdrop closes.
- [ ] `SEED_LIBRARY` (echoes user's screenshot): `vellum-workspace-upgraded.html` (code, Monday, 197 KB), `vellum-workspace.html` (code, Monday, 184 KB), `Corrected_Bank_Guarantee_Request.pdf` (pdf, 03/06, 2.42 KB), `Bank_Instrument_Request_Letter.pdf` (pdf, 03/06, 295 KB), `vellum_ui_patch.diff` (diff, 02/06, 44.8 KB), `vellum_preview.png` (image, 02/06, 137 KB), plus 2 notes.
- [ ] `LibraryView`: header `Library` + right: search input, `New ⌄` (menu: Upload → file picker appends item; Note → appends note with inline-rename armed). Tab row All/Images/Files + right filter glyph (no-op dim) + grid/list toggle.
- [ ] List view: header columns Name / Modified ↓ / Size; rows with kind icon (code/pdf/diff/image/note), hover highlight, `⋯` → Rename (inline) / Delete.
- [ ] Grid view: tiles (kind glyph large, name, modified).
- [ ] Filters: tab Images → `kind==='image'`; Files → everything non-image; search filters name.
- [ ] Verify compile + manual: tabs/search/views/Upload/Note/rename/delete. Commit + push.

## Task 5: Projects page
**Files:** Modify `vellum-default.html`.
- [ ] `SEED_PROJECTS`: `Vellum Desktop` (12 notes, updated Monday), `Reading — Meditations` (7, 04/06), `Sports daemon` (4, 28/05).
- [ ] `ProjectsView`: header `Projects` + `New project` button (appends "Untitled project", inline-rename armed); card grid (name, `{n} notes`, updated). Card click = no-op.
- [ ] Verify compile + manual. Commit + push.

## Addendum tasks (10/06/2026, second pass — spec Addendum B)

### Task 7: Conversation timeline (spec B1)
**Files:** Modify `vellum-default.html`.
- [ ] Give each user message DOM id `m-<msg.id>`.
- [ ] `Timeline` component, absolutely positioned mid-right inside `.main` (which is `position:relative`): one `.tl-bar` per user message (width 8–22px by text length); wrapper hover opens `.tl-pop` — scrollable list of truncated user prompts; row click → `scrollIntoView({behavior:'smooth'})`; render only when ≥ 2 user messages.
- [ ] Verify compile + manual. Commit + push.

### Task 8: Rail flyouts + sidebar Projects section (spec B2)
**Files:** Modify `vellum-default.html`.
- [ ] Replace sidebar "Projects" nav row with a Projects section: `.sb-sec` header (click → projects page), `New project` row (creates + arms inline rename), project rows with hover `⋯` → `ProjectMenu` (Share project dim-hint / Rename project inline / Delete project red). Project rename/delete shared with Projects page state.
- [ ] Rail: add chats icon with hover flyout "Recents" (last 10, pinned-first, click opens); projects icon hover flyout (New project + rows with `⋯` menu); flyouts are absolutely positioned panels inside a `position:relative` rail wrapper, open on mouseenter, close on mouseleave.
- [ ] Verify compile + manual. Commit + push.

### Task 9: Animated placeholder + generation glow (spec B3 + B4)
**Files:** Modify `vellum-default.html`.
- [ ] Composer: remove static placeholder; when `text` empty render pointer-events-none overlay span cycling `PLACEHOLDERS = ['ask.','what are you reading.','write, or edit.','search your library.','sit with a question.']` every 3s, re-animated via `key={i}` + `@keyframes phIn` fade-up.
- [ ] Glow: dark `.areply.shimmer` gains `filter:drop-shadow(0 0 7px rgba(227,93,43,.40))`; light theme override disables shimmer entirely (`background:none; color/-webkit-text-fill-color: var(--txt); animation:none; filter:none`).
- [ ] Verify compile + manual (both themes). Commit + push.

### Task 10: Smoke coverage for addendum
**Files:** Modify `smoke-default.mjs`.
- [ ] New checks: timeline bars + popup rows + jump (2-message thread); rail recents flyout (≤10 rows, opens chat); sidebar Projects section (new/rename/delete project); animated placeholder present + rotates within 5s; light-mode streaming text visible (computed text fill not transparent).
- [ ] Run full suite → all PASS. Commit + push.

## Addendum C tasks (10/06/2026, third pass — spec Addendum C)

### Task 11: Project model + Create-project modal + sidebar nesting + menus
**Files:** Modify `vellum-default.html`.
- [ ] `chats[].projectId` (null default); `projects[]` gain `memory:'default'`, `sources:[]`. `visibleChats` excludes `projectId` chats (Recents/rail/search untouched by project chats).
- [ ] `CreateProjectModal`: name input ("Copenhagen Trip" placeholder), gear → memory popover (Default ✓ / Project-only, "can't be changed later" note), hint card, Create disabled until named → `createProject({name, memory})` → opens project page. All "New project" entry points open this modal.
- [ ] Sidebar: project chats render indented (`.chat-row.nested`) under their project row; `ChatMenu` gains `Remove from {project}` for project chats (`action:'removeproj'` → `projectId=null`). Project row click → `openProject(id)`; grid cards too; delete project moves its chats to Recents.
- [ ] Verify compile. Commit + push.

### Task 12: Project page + in-project chat + breadcrumb + sources
**Files:** Modify `vellum-default.html`.
- [ ] `view:'project'` + `activeProjectId`. `ProjectPage`: folder+name header (dim "project-only memory" label when set), Composer with static `ph="New chat in {name}"` → `sendMessage(text, attach, projectId)` then open the new chat; tabs Chats/Sources + dim "Newest ⌄"/"All ⌄" chips; Chats tab rows/empty state; Sources tab dashed card ("Give Vellum more context" + Add sources file picker) and source rows; sources also append to Library.
- [ ] `ChatView` breadcrumb strip (folder glyph + project name) when the open chat has a `projectId`; ProjectsView cards show live chat counts and open the page.
- [ ] Verify compile. Commit + push.

### Task 13: Smoke coverage for projects
**Files:** Modify `smoke-default.mjs`.
- [ ] New checks: Create-project modal (name + Project-only memory) → project page opens; "New chat in" composer creates nested chat (sidebar indent, breadcrumb, absent from Recents); Remove from project moves chat to Recents; Sources tab Add sources via `setInputFiles` → row + Library entry; delete project keeps its chats in Recents. Update older checks that assumed inline-rename project creation.
- [ ] Full suite green. Commit + push.

## Addendum D tasks (10/06/2026, fourth pass — spec Addendum D)

### Task 14: Sidebar sections — Coding link, Ledger, Skills, Memory, Archive
**Files:** Modify `vellum-default.html`.
- [ ] Seeds: `SEED_SKILLS` ({proposed, active, retired} arrays with name/trigger/uses/last fields per CLAUDE.md skill JSON), `SEED_MEMORY` (portrait facts with category), ledger dummy numbers.
- [ ] Sidebar nav rows after Library: Coding (→ `window.location.assign('vellum-workspace.html')`), Ledger, Skills, Memory, Archive (views). Rail icons for Coding/Ledger/Skills/Memory.
- [ ] `LedgerView`: stat rows (today tokens+cost, thread tokens, recent models i./ii./iii., week totals) + footer "Filed locally. Nothing sent."
- [ ] `SkillsView`: tabs Proposed/Active/Retired; Approve moves proposed→active; Retire moves active→retired; counts in tabs.
- [ ] `MemoryView`: fact rows (category chip + text + Forget trash) + stats line + privacy footer.
- [ ] `ArchiveView`: archived chats with Restore/Delete; empty state.
- [ ] Compile gate. Commit + push.

### Task 15: Settings modal
**Files:** Modify `vellum-default.html`.
- [ ] `SettingsModal` (two-pane): General (theme control, plan, app line) · Reflections (dummy digest/reflection/provocation entries) · Saved (list) · Feeds (X/YouTube/Sports rows + switches, preview note) · Computer use (status pill, Enable/Stand down, Ctrl+Alt+Esc note, preview note).
- [ ] Profile popover Settings row → opens modal (no longer dim); Esc/backdrop close; feeds + computer-use state in App.
- [ ] Compile gate. Commit + push.

### Task 16: Smoke coverage for sections + settings
**Files:** Modify `smoke-default.mjs`.
- [ ] Checks: Coding row present with workspace title (no navigation); Ledger renders footer line; Skills approve → Active count up; Memory forget → fact count down; archive chat → Archive view → Restore → back in Recents; Settings modal via profile (tabs, X-feed toggle, Computer use enable → active pill).
- [ ] Full suite green. Commit + push.

## Addendum E tasks (10/06/2026, fifth pass — spec Addendum E)

### Task 17: Token + font overhaul
**Files:** Modify `vellum-default.html`.
- [ ] Google Fonts `<link>` (Bricolage Grotesque 500–700, Schibsted Grotesk 400–600, Spline Sans Mono 400–500); `--font-d`/`--font-m` vars; body → Schibsted Grotesk.
- [ ] Replace `:root` + `[data-theme=light]` token blocks (ink-blue darks, mint/cyan accent, coral danger, `--glass`, `--glow`, `--onaccent`); `replace_all` `var(--ember)`→`var(--accent)`, `var(--onember)`→`var(--onaccent)`; regrade hardcoded ember colors (appmark, rail-dot, shimmer glow, cu-pill, send/primary gradients, avatar gradients).
- [ ] Compile gate. Commit + push.

### Task 18: Glass, motion, typography scale, copy
**Files:** Modify `vellum-default.html`, `smoke-default.mjs`.
- [ ] Glass override block (ctx-menu/pop/search-card/flyout/tl-pop/gear-pop/mode-menu/modal/set-modal → `--glass` + blur + `popIn` entrance); composer focus ring; `.main` mint atmosphere radial.
- [ ] Display type on wordmark/landing/page/project/modal/section titles; mono on ledger values + mem-stats; greeting → "Ready when you are." (gradient land-mark, no italics); PLACEHOLDERS → modern copy.
- [ ] Smoke: update greeting assertion (+ glow check label); full suite green. Commit + push. Screenshots + memory.

## Addendum F tasks (10/06/2026, sixth pass — spec Addendum F)

### Task 19: Model picker
**Files:** Modify `vellum-default.html`.
- [ ] `MODELS` const + `modelLabel()`; app-level `selModel` state passed to ChatView/ProjectPage; Composer replaces mode chip with `.model-pill` → `.model-drop` (drop-lbl "Model"/"↻ Sync" dim, `.model-search`, `.model-list` with ✓, "Manage models & keys…" dim footer). Remove ModeMenu/mode state.
- [ ] Compile gate. Commit + push.

### Task 20: Collapsible sections + animated folders
**Files:** Modify `vellum-default.html`.
- [ ] `.sb-scroll` wraps Projects + Recents sections (nav fixed above, profile pinned below); `secOpen` app state; chevrons (Projects: label→grid, chevron→toggle; Recents: header→toggle).
- [ ] `IcFolderOpen` + `FolderIcon` crossfade component; `expandedProj` app state; ProjectRow icon click toggles (stopPropagation), row click navigates; nested chats render only when expanded; auto-expand on project create + in-project chat create.
- [ ] Compile gate. Commit + push.

### Task 21: Smoke for F
**Files:** Modify `smoke-default.mjs`.
- [ ] Checks: model picker search+select updates pill; Recents header collapse hides rows/re-expand shows; folder icon toggle hides/shows nested chat (inside Smoke-project flow).
- [ ] Full suite green. Commit + push. Screenshot + memory.

## Addendum G tasks (10/06/2026, seventh pass — spec Addendum G)

### Task 22: Toggle behavior (spec G1)
- [ ] ProjectRow: row click → `onToggle()` + `onOpen()` (icon has no separate handler); Projects `.sb-sec` click → `onToggleSec('projects')` (chevron same).
- [ ] Smoke: "projects grid" navigates via rail projects icon; "remove from project" expands the folder (row click) before hovering the nested row. Compile + suite-relevant checks. Commit + push.

### Task 23: + dropdown, attachments, lightbox (spec G2+G3)
- [ ] `PlusMenu` (glass, above +): Add photos & files → fileRef; Recent files › submenu ("Add from library" → Library view; top-3 library items, click attaches `{name,size,kind}`); Create image / Deep research / Web search dim rows; Projects › submenu → `openProject`.
- [ ] Attachment model gains `url` (createObjectURL for image/*); `.att-card` + `.att-img` strip in composer; message bubbles render image thumbs / file cards; `Lightbox` (App-level `viewer` state, `onViewImage` passed down; Esc/backdrop closes).
- [ ] Compile gate. Commit + push.

### Task 24: Apps connectors (spec G4)
- [ ] `SEED_APPS` (airtable off · github setup · linear off · box/dropbox/gmail connect) + per-app mini icons; `AppsDrop` (toggle `.sw` for on/off; "Finish Setup"/"Connect" buttons → state on; "Connect more" hint); Apps ⌄ chip after +; enabled apps as `app-chip`s (icon+name+⌄ → reopen dropdown).
- [ ] Compile gate. Commit + push.

### Task 25: Sizing + smoke (spec G5)
- [ ] Icon default 17; font-size bumps (body/sidebar/composer/replies/menus); padding adjustments.
- [ ] New smoke: + menu attach-from-recents card + remove; tiny-png upload → thumb → lightbox open/Esc; GitHub Finish Setup → chip appears; Airtable toggle on/off chip. Full suite green. Commit + push. Screenshot + memory.

## Addendum H tasks (10/06/2026, ninth pass — spec Addendum H)

### Task 26: Whole-sidebar scroll
- [ ] Move nav rows into `.sb-scroll` (header + profile pinned). Smoke: `.sb-scroll .sb-row` "New chat" exists. Commit + push (with Task 27/28).

### Task 27: Slash menu
- [ ] `SLASH_ITEMS` (files/run + thinking/image/web/study dim); `SlashMenu` (compact, `.slash-menu`+`.down`, no backdrop, label-filter on text after `/`); Composer: `slashDismissed` state (Esc dismisses, text change resets); file item → picker + clear text; dim items dismiss.

### Task 28: App-chip rework
- [ ] Replace per-app chips: 1 on → `⊗ Name ⌄` (⊗ = toggle off; click → picker/GitHub panel); >1 → `{n} apps ⌄` → `AppsPicker` (✓ rows toggle off; GitHub row › → `GitHubPanel` with repo search/empty state/dim config rows). Compile + full smoke (update apps check; add slash + scroll asserts). Commit + push. Screenshot + memory.

## Addendum I tasks (10/06/2026, tenth pass — spec Addendum I)

### Task 29: Popover primitive + caret (spec I3+I6)
- [ ] `Popover` component (ref div, document mousedown outside → onClose); replace backdrop+div pairs in PlusMenu, AppsDrop, AppsPicker, GitHubPanel, ModelDrop, ChatMenu, ProjectMenu, ProfilePopover, ChatMenu/lib item menus. `.ph-anim{left:10px;top:8px}`.
- [ ] Smoke: remove `.backdrop` click in + menu check (use Escape); add one-click switching assert (apps open → click + → plus menu visible in one click). Commit + push.

### Task 30: Per-chat apps + slash connectors + project hover pencil (spec I1+I2+I4)
- [ ] `apps[].state → ready/setup/connect` (airtable+linear ready); `chats[].appIds` + `draftApps`; selection helpers (toggleSel/connectApp); directory switches read selection; chip + picker read per-chat selection; sendMessage transfers draft.
- [ ] SlashMenu: apps section (select/connect+select) + Projects {n} › submenu; ProjectRow hover pencil before dots → onOpen.
- [ ] Smoke: rewrite apps check for selection model + per-chat isolation (chip absent on other chat); slash shows app + Projects rows. Commit + push.

### Task 31: Back/forward nav (spec I5)
- [ ] History stack of `{view, chat, proj}` in a ref (push on change unless silent), ← → titlebar buttons with disabled ends.
- [ ] Smoke: open Library → chat → back twice → forward; assert views. Full suite green. Commit + push. Screenshot + memory.

## Task 6: Profile popover + Edit-profile modal + final polish
**Files:** Modify `vellum-default.html`.
- [ ] `ProfilePopover` (anchored above profile row): email line; account row (avatar, displayName, IcCheck) ; `Add account` (dim hint "not in this preview"); divider; rows Upgrade plan / Personalization / **Profile** / Settings / Help / Log out — all dim-hint no-ops except Profile → opens Edit-profile modal.
- [ ] `EditProfileModal`: dimmed backdrop, centered card — `Edit profile` title, avatar circle (initials, camera badge bottom-right), labeled inputs Display name + Username (controlled, prefilled), helper "Your profile helps people recognize you in group chats.", Cancel / Save (ember). Save commits to `profile` (initials + sidebar name update); Esc/Cancel/backdrop discards.
- [ ] Polish pass: Esc closes any open overlay/menu; click-outside closes popovers; light theme checked on every surface (sidebar, rail, chat, library, projects, overlays, modals); scrollbar styling; empty Recents state ("No chats yet.").
- [ ] Full manual run-through per spec §9 checklist (both themes).
- [ ] Verify compile. Commit + push.
