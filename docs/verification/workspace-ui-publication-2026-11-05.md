# Sidebar, composer and workspace publication - 2026-11-05

This change continues `codex/electron-workspace-startup` after PR #239 merged. The branch starts from current main, preserving the patched Electron dependency and parse5 desktop compiler. Previously merged Electron startup, original ProseMirror integration, typed connector metadata and layout work remain in its history.

Included remaining work:

- Shared destination rail, contextual hover sidebars, stable interactive project/chat cards, section controls and quick chat actions.
- Library grid/list browsing, filters, previews and shared dropdown surfaces; session-only attachment organization remains disclosed.
- Bundled SN Pro typography across the interface, with its license and provenance.
- One context-aware keyboard/command registry used by Electron, browser guests, command search, shortcut references and tooltips.
- Vendor artwork, structured slash/reference selection, scoped Escape back-navigation and inline caret alignment.
- Durable project folders and membership through the conversation writer and typed actions; guarded creation, revision checks and confirmed removal that retains chats.
- Startup workspace visibility, full/split restore, independent tab closing, side-chat drafts using the shared composer, direct search destinations and read-only local-drive previews.

Publication was assembled in an isolated worktree. Unrelated development voice, compaction, integration, account and media changes were not copied. Existing main voice behavior is retained in both composers. Generated bundles, installed runtimes, personal profiles, logs, databases and caches are excluded.

Verification during publication is static only: JavaScript/JSX and CSS parsing, comparison of newly unbound HTML names against main, Python syntax parsing, Action Parity source/probe review and whitespace inspection. No tests, build, signed-in browser interaction or desktop operation was rerun for publication. Prior local/component evidence is recorded in the adjacent sidebar, command, composer and workspace verification notes; those results are not a claim that this assembled commit passed hosted CI or a full regression suite.

Installation, updates, live provider/voice acceptance and clean-machine verification remain outside this publication. This commit does not add persistent cloud-file management or grant an agent unrestricted filesystem access.
