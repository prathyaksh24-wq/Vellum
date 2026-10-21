# Title bar and account identity presentation — 2026-10-21

The draft PR was isolated from the shared checkout onto main at 179def8.
Its scope is Windows window chrome and account identity presentation only.
Dictation, live voice, streaming, embeddings, profile migration, protected music
playback, plugin setup and other unrelated changes are excluded.

Windows workspace and detached-conversation windows use a 38px themed draggable
bar. Native caption controls remain provided by Electron's title-bar overlay.
The renderer exposes Vellum/Edit/View/Window menus, keyboard traversal and visible
menu-open failures. Preload exposes only named menus and opaque theme colors;
main-process handling checks registered workspace/conversation windows, trusted
top-level frames, allowed IDs and bounded menu coordinates. Other desktop window
types and ordinary browser pages retain their existing frame behavior.

Accounts settings show the current identity first under Signed in as, followed
by explicitly inactive Saved on this device identities. Guest access never marks
a saved account as signed in. The profile picker uses the same current-first
ordering and Active/Saved labels. Existing sign-in, switch, logout and removal
flows retain their canonical Accounts API. No backend identity contract, provider,
credential, workspace partition or content-sync behavior changes.

No tests, builds, native smoke runs or UI automation were executed during this
publication, as explicitly requested. Existing desktop chrome and mounted UI
regression test sources are included but were not run on this branch. Diff and
file-scope inspection are publication checks, not runtime validation. Existing
mainline authentication validation does not establish this presentation change.

Manual gates remain: Windows native menu/caption behavior, theme changes,
conversation windows, keyboard/focus handling, native browser overlap, and
signed-in/guest layouts at desktop and narrow widths. Main/preload changes need
an Electron restart; Ctrl+R alone cannot load the native title bar changes.
No new screenshots were generated during publication.
