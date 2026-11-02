# Electron workspace publication - 2026-11-02

This draft follows the Electron migration already merged in PR #224. It is based on current main and preserves the later merged chat, voice, connector and dependency fixes.

## Included changes

- Standalone Electron startup with a packaged backend, explicit existing-data workspace selection, backend build/protocol handshake, workspace ownership lock, tray lifecycle and logs.
- Compiled desktop UI, aligned title bar and session navigation, opaque settings surfaces and reduced covered-background work.
- Container-measured browser split with bounded pane sizes, responsive drawer mode, draggable sidebar and keyboard resizing. Native browser bounds updates stay serialized during resizing.
- ProseMirror composer with categorized slash commands and mention providers, portal positioning, input-width menus, stable keyboard/trackpad scrolling, coordinated corners, branded references and no composer memory button.
- Shared plugin/app/MCP/skill ownership classification in the composer and plugin settings, with typed reference metadata carried through the existing attachment path.

## Static publication review

The branch was assembled in an isolated worktree. Only task-related paths were selected. Generated desktop packages, runtime payloads, local profiles, credentials, databases and unrelated source-checkout work are excluded.

Changed UI handlers continue to use the existing App Action and composer send paths. Draft selection, navigation, resizing and menu presentation remain local UI operations. Selected reference metadata does not fetch content or execute connector tools. Action Parity source registration and fingerprints were updated for these reviewed sources.

No tests or builds were run during PR preparation, as requested. Earlier development evidence is recorded in the individual verification notes; it does not establish that the combined publication branch has passed validation.

Installation remains deferred. Signed installer distribution, automatic updates, clean-machine installation and attended long-session desktop/browser verification remain future work.
