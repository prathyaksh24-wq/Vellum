# Vellum Default-Mode Shell (ChatGPT-style home) — Preview

**Date:** 10/06/2026
**Status:** Approved design — ready for implementation plan
**Surface:** NEW standalone file `design/Velllum/uploads/vellum-default.html` (separate from `vellum-workspace.html` and `vellum-coding.html`)
**Nature:** Front-end preview only. No Tauri, no backend, no network. Fully self-contained, web-previewable. This is the **default mode** — the first screen the user sees when the desktop app opens.

---

## 1. Goal

A convincing, interactive preview of Vellum's **default mode**: the ChatGPT-style home shell
(per the user's reference screenshots, dark + light), rebranded and re-voiced as Vellum.
Desktop-app chrome wraps a web view — matching how the real app runs (Tauri webview over
`D:\Vellum` frontend).

The reference is ChatGPT's shell with these explicit edits from the user:

- Sidebar **excludes** Apps, Codex, GPTs, and "… More".
- Sidebar **includes**: New chat, Search chats, Library, Projects, and Recents (chat history).
- Collapsed-sidebar state (thin icon rail) included.
- **Library** page: where all external sources used inside chats live (files, images, notes) —
  All / Images / Files tabs, search, "New ⌄" (Upload / Note), list + grid views,
  Name / Modified / Size columns.
- **Profile** section (bottom of sidebar) with account popover, and an **Edit profile** modal
  (avatar with initials + camera badge, Display name, Username, Cancel/Save).
- Dark mode **and** light mode.

## 2. Non-goals

- No coding-assistant mode in this file (that's `vellum-coding.html`; a sidebar entry may
  deep-link nowhere / show a quiet "separate preview" note, but no IDE UI here).
- No real chat backend — replies are canned, brand-voiced, streamed character-wise.
- No real uploads — Upload adds a dummy row (client-side file picker reads name/size only).
- No Tauri packaging; previewable as a plain `.html`.
- Not a modification of `vellum-workspace.html`.

## 3. Shell

Same desktop chrome family as `vellum-coding.html`: stage backdrop → window (titlebar with
app mark, centered title, window controls) → body. Body = sidebar + main. A sun/moon toggle
in the titlebar switches dark/light; theme is a CSS-variable swap on the root (`data-theme`),
persisted to `localStorage`.

**Brand register:** Vellum voice everywhere — lowercase wordmark "vellum", ember accent,
no exclamation marks, no "Hi there!". Landing line: **"What are you reading."**
(canonical Vellum landing, replacing ChatGPT's "Ready when you are.").

## 4. Sidebar

### 4.1 Expanded (~260px)
- Header row: `vellum` wordmark + collapse button (panel icon, right-aligned).
- Nav: **New chat** (pencil-square icon) · **Search chats** (magnifier) · **Library**
  (book/stack icon) · **Projects** (folder icon).
- **Recents** section label, then chat rows (title, ellipsised). Active chat highlighted.
  Hover shows `⋯` → context menu: **Share · Rename · Pin chat · Archive · Delete** (Delete in
  red). Pinned chats sort to top with a small pin glyph. Rename is inline (input swap).
- Bottom: **profile row** — avatar circle (initials), display name, plan ("Private"), and a
  small edit-profile glyph on the right. Click → profile popover (4.4).

### 4.2 Collapsed (icon rail, ~52px)
Logo mark (click → expand), then icon-only: new chat, search, library, projects.
Avatar at bottom. Tooltips on hover. State toggles via the collapse button / logo.

### 4.3 Search chats
Modal overlay (ChatGPT-style): input on top, live-filtered list of chats below ("New chat"
row first). Enter/click opens the chat. Esc closes.

### 4.4 Profile popover
Anchored above the profile row:
- Account block: email (`openslides.ai@gmail.com` dummy), account row with ✓, **Add account**.
- Divider, then: **Upgrade plan · Personalization · Profile · Settings · Help · Log out**.
- **Profile** opens the Edit profile modal. Others are quiet no-ops (toast "Filed away for
  later." is *not* brand; instead a dim inline "not in this preview" hint or simply nothing).

### 4.5 Edit profile modal
Centered card over dimmed backdrop: large avatar circle with initials + camera badge,
**Display name** field, **Username** field, helper line "Your profile helps people recognize
you in group chats.", **Cancel / Save**. Save updates state (sidebar row, avatar initials).

## 5. Main views (in-file router)

`view: 'chat' | 'library' | 'projects'` plus `activeChatId`.

### 5.1 Chat — landing (no messages)
Centered: greeting **"What are you reading."**, composer pill (+ button, "ask." placeholder,
mic icon, ember voice/send button, mode chip "Extended ⌄" → Extended/Instant dummy menu),
and three action chips below: **Write or edit · Look something up · From your library**.
Chips prefill the composer.

### 5.2 Chat — thread
User bubbles right-aligned; Vellum replies as plain prose (no bubble), streamed
character-wise with a working shimmer, followed by action icons (copy, thumbs up/down,
share, regenerate — copy and regenerate functional; regenerate re-streams a variant).
Replies are canned Vellum-voice texts keyed off simple keyword buckets, with the user's
words woven in. Composer docks to bottom in thread mode.

`+` in the composer opens a file picker; the chosen file is added to **Library** (name,
size, modified = today) and shown as an attachment chip on the next user message —
this is the "external sources used inside chats land in the Library" behavior.

### 5.3 Library
Header: **Library** title; right: search input ("Search library"), **New ⌄** dropdown
(**Upload** → file picker, **Note** → creates a note row and a small inline name prompt).
Below: tabs **All / Images / Files**, then right-aligned filter glyph + grid/list toggle.
- **List view**: columns Name (icon by type: code/pdf/image/diff/note), Modified, Size;
  hover row highlight; `⋯` per row → Rename / Delete.
- **Grid view**: tile per item (type glyph, name, modified).
- Search filters by name; tabs filter by kind (`image` vs everything-else for Files).
- Seeded with dummy data echoing the user's screenshot (`vellum-workspace-upgraded.html`,
  `vellum-workspace.html`, PDFs, `vellum_ui_patch.diff`, `vellum_preview.png`, …) with
  DD/MM-style "Modified" labels (Monday, 03/06, …).

### 5.4 Projects
Minimal: **Projects** title, "New project" button (creates a dummy card), grid of project
cards (name, note count, updated). Clicking a card is a quiet no-op for this slice.

## 6. Theming

Two palettes on CSS variables:
- **Dark (default):** near-black graphite stage (`#0d0d0d` family), parchment-grey text,
  ember `#e35d2b` accent — consistent with `vellum-coding.html`.
- **Light:** parchment whites (`#f7f5f0` family), ink text (`#26241f`), same ember accent.
Titlebar sun/moon toggles `data-theme="light"`; persisted via `localStorage('vellum-theme')`.
All components read only the variables — no hardcoded per-theme colors in components.

## 7. State (in-memory, one store)

```js
state = {
  theme:'dark'|'light', sidebar:'open'|'rail', view:'chat'|'library'|'projects',
  activeChatId, chats:[{id,title,pinned,archived,messages:[{role,text,attachments?,ts}]}],
  library:[{id,name,kind:'html'|'pdf'|'diff'|'image'|'note',size,modified}],
  projects:[{id,name,notes,updated}],
  profile:{displayName,username,email,plan}
}
```
Theme persists to localStorage; everything else is session-only dummy data (preview).

## 8. Honesty / errors

- No fake "uploading…" progress; Upload files appear instantly (it's a preview).
- Buttons that do nothing in this slice (Share, Personalization, Settings, Help, Upgrade,
  Add account, Log out) get a dim one-line note, never a fake success.
- The titlebar says "vellum — preview" so it is never mistaken for the live app.

## 9. Testing / verification

1. **Compile gate** — `node design/Velllum/uploads/check-default.mjs` (esbuild JSX check)
   → `OK: JSX compiles`.
2. **Manual run-through** in a browser:
   - Opens to dark landing: wordmark, greeting, composer, chips; sidebar with New chat /
     Search chats / Library / Projects / Recents; profile row at bottom.
   - Send a message → user bubble + streamed Vellum reply; copy + regenerate work.
   - `+` attach → file lands in Library and shows as a chip.
   - Collapse sidebar → icon rail; expand again.
   - Search chats overlay filters and opens chats; Esc closes.
   - Recents `⋯`: rename inline, pin (sorts to top), archive (hides), delete.
   - Library: tabs, search, list/grid toggle, New → Upload and Note.
   - Profile popover → all rows; Profile → Edit profile modal; Save updates name/initials.
   - Theme toggle → light mode everywhere (sidebar, chat, library, modals), persists reload.

## 10. Out of scope (explicit)

Coding mode UI, terminal/browser workspace tabs, progress bars for agent runs, real SDKs,
real uploads/storage, Tauri wiring, group chats, voice capture. Later slices unify this
shell with `vellum-coding.html` inside the Tauri desktop app.

---

## Appendix A — Brainstorm audit (9 lenses)

1. **Intent** — User asked for ChatGPT-shell parity with listed deletions/additions, default
   mode first. Spec mirrors each screenshot element and names the exclusions. ✓
2. **Scope/YAGNI** — Coding mode, real backend, group chats excluded; Projects page kept
   minimal (sidebar parity requires it, nothing more). ✓
3. **Brand** — ChatGPT copy replaced with Vellum register ("What are you reading.", "ask.",
   Private plan, no exclamations); ember + graphite/parchment palettes. ✓
4. **Consistency** — Same chrome, stack (React UMD + Babel), file location, and compile-gate
   pattern as the approved `vellum-coding.html` slice. ✓
5. **Feasibility** — Single-file React with one store; no API surface; all interactions are
   local state transitions. Nothing speculative. ✓
6. **Isolation** — Components: Titlebar, Sidebar(+Rail), ChatView, Composer, LibraryView,
   ProjectsView, SearchOverlay, ProfilePopover, EditProfileModal — each reads the store via
   props; theme via CSS vars only. ✓
7. **Error handling/honesty** — No-op buttons say so; preview labeled; no fake progress. ✓
8. **Testability** — Compile gate + scripted manual checklist (§9) covering every
   interactive element. ✓
9. **Future-fit** — View router + store shape map 1:1 onto the planned unified Tauri shell;
   light theme tokens introduced now will be reused by the workspace later. ✓
