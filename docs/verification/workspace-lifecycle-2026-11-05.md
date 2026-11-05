# Workspace lifecycle and side chat — 2026-11-05

Implemented in the existing workspace/conversation owners:

- Saved browser/workspace panes start hidden with split presentation; retained items are not deleted.
- Full view has Restore split view and Hide controls. Escape restores split view after higher-priority popup handling.
- Workspace commands target the selected content tab. Shared BrowserPanel close actions delegate to the workspace owner, retaining non-browser tabs.
- A navigation-only conversation.new receipt creates an ordinary local draft for side chat. It uses ChatView/Composer, existing send/persistence, connector controls, model/reasoning controls and scoped voice callbacks.
- Launcher search supplies its destination to browser creation. A running browser creates the URL directly; a closed browser navigates before its pane is presented.
- Files offers On this device and Chat files. Read-only local_files IPC is restricted to a registered top-level workspace renderer. It lists one local-drive directory and provides bounded text/image previews. It does not mutate files or grant the agent filesystem access.

Verification:

- 30 focused frontend checks passed (workspace lifecycle, controls, app-action runtime).
- 21 desktop checks passed (local file boundaries, policy, commands).
- Isolated compiled UI in muted headless Brave, fake APIs and no external network: two shared composers, side-chat shortcut, restore full to split, independent button and Ctrl+W tab closing, synthetic C: file preview; no page errors.
- Desktop UI build passed; existing chunk-size warning remains. Action Parity validation and scoped diff whitespace checks passed.
- Broader legacy HTML-source suite: ten source-string assertions remain failing against this heavily modified checkout. These are not represented as passing; the focused checks do not replace a full-suite run.
- User-approved app launch completed: Electron PID 23456, backend PID 51360; /api/desktop/runtime confirmed the nested existing workspace; bundled UI on 5184 returned HTTP 200.

Limits: no live provider, voice, personal-file or signed-in-site interaction was tested. Live desktop UI was not operated. Changes remain local and uncommitted.

Proposed PR title: Fix workspace tab lifecycle and share the main composer with side chat

Proposed description: Prevent saved workspace panes from reopening on startup and route tab closing through the active workspace owner. Add full-view restore controls, create side-chat drafts through the existing conversation flow, and reuse the main composer controls. Add bounded, user-directed local-drive browsing through the trusted Electron bridge and pass launcher searches directly to their results URL. Verification and limits are recorded above.
