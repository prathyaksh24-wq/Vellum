# Workspace content views and click correction — 2026-11-03

This extends the earlier browser-only workspace implementation. Current source
and the desktop bundle now use a New tab **content pane**, not a dropdown.

## Implemented behavior

- The chat interface retains the requested control order: chat options, a summary
  glyph matching the supplied circles-and-lines reference, and New tab. These
  controls stay below the native title bar. The overlay header no longer reserves
  an empty horizontal band.
- New tab opens a retained, typed launcher view beside the chat. Its address form
  uses the existing browser adapter; its Files/previews, Side chat, Terminal and
  Browser choices replace that launcher with actual content. No floating tab
  chooser remains. Split view has a content tab strip; full view also retains
  the current main chat as the first tab.
- Workspace Layout owns the bounded `items` and `active_item` references on the
  existing right-panel surface. `WorkspaceContentTab` validates identities,
  supported kinds and bounded labels; content stays with its existing owner.
- Side chats use the existing conversation lifecycle, writer, send queue,
  streaming updates, cancellation and conversation-scoped model/reasoning
  actions. They do not replace main-chat navigation or its model label. Existing
  side conversations hydrate through `conversation.open` without navigation.
- Files project real attachments, saved file content, artifacts and fenced code
  from the selected chat or library. Image/text/PDF and static HTML previews
  reuse those records; HTML runs in a sandbox with scripts disabled. Unsupported
  files show an explicit missing-preview state and a download when available.
- Summary displays an existing summary when supplied, otherwise a labeled
  conversation outline with jumps to actual user messages. It does not invoke a
  model or compact history merely to open the panel.
- The existing terminal workspace and TerminalSessionManager provide local shell
  sessions. Embedded input goes directly to the PTY, supports resize, preserves
  terminal instances while switching/hiding views, and disposes sessions when
  their owning workspace view closes. Windows retains WinPTY and available
  PowerShell/CMD/PowerShell Core/Git Bash profiles. macOS/Linux select the native
  configured shell and use a controlling POSIX PTY. Optional Windows macOS SSH
  remains distinct from native local macOS shell selection.
- Terminal capability/profile discovery comes from the backend. The existing
  WebSocket checks loopback client and canonical local-preview origins. Direct
  user shell I/O remains on this dedicated transport and is explicitly deferred
  from generic App Action parity; it is not a model tool.
- Panel enter/leave motion respects reduced motion and suspends native guest
  mounting during layout movement. Music controls remain available when browser
  presentation opens; overlapping dock/music UI participates in native guest
  occlusion handling.

## Reported unclickable New tab

Removing the old dropdown CSS also removed a combined selector that restored
pointer input to header children. The header itself deliberately has
`pointer-events:none` so its empty area does not cover content. The running
New tab button consequently inherited `pointer-events:none`.

A read-only DOM/CSS diagnostic against the actual Vellum page observed:

| State | Display | Visibility | Pointer events |
|---|---|---|---|
| Before correction | flex | visible | none |
| Rebuilt/reopened correction | flex | visible | auto |

The correction explicitly restores pointer input to header buttons, inputs, tab
rows and the error region, independently of deleted dropdown classes. No click,
script evaluation, model query or shell command was sent through that diagnostic.

## Verification and limits

- Source parsing passed for the main JSX and modified JavaScript/JSX, CSS and
  Python sources; modified Python was parsed without importing the API.
- The desktop UI build succeeded and was copied to `desktop/resources/ui`.
- The updated app was reopened using the existing workspace/profile and normal
  source host. Startup reported backend readiness. Read-only runtime identity
  matched the nested workspace; terminal capability and installed Windows shell
  profile metadata were available.
- Passive REA capture showed the updated landing layout without the old Tabs
  label/top band. The later live CSS diagnostic confirmed restored pointer input.
- Reviewed the served-handler delta, registered the new module-backed terminal
  and content sources, and recorded canonical action mappings or the explicit
  terminal transport limitation. Unrelated source locks were preserved.
- Whitespace review reported no errors on the affected tracked source paths.

**No automated tests were run.** Full click-through review was unavailable because
the Windows Computer Use tool reported that Electron app control was not approved.
Terminal command execution, macOS/Linux execution, responsive interactive flows,
panel animation quality and packaged clean-install behavior are not claimed as
verified. No tests, model calls, playback mutations or terminal commands were
performed as substitutes. Existing unrelated dirty-tree changes were preserved;
no commit, push or PR was created.

## Proposed PR

Title: Add pane-based workspace tools and native local terminals

Description: Replace the tab dropdown with a retained New tab content pane and
shared split/full tab strips. Integrate real file previews, side conversations
and the existing local terminal owner; retain independent summary and music
controls, add bounded panel motion, and restore pointer interaction on the chat
header. Extend shell discovery and PTY transport for native Windows/macOS/Linux
execution. Desktop build, syntax review, startup metadata and read-only pointer
inspection succeeded. Tests and interactive/macOS acceptance were not run.

## Draft preparation — 2026-11-04

The draft was isolated on current main (`c4c353d`) rather than copying the dirty
checkout wholesale. Existing merged interface and Electron startup corrections
were retained. Only workspace/interface edits and their direct contracts,
dependencies and fixture loaders were transferred. No test suite or build was
run during draft preparation. Earlier build and runtime observations above
belong to the implementation checkout, not this exact rebased PR commit.

Static integration review found that ordinary `conversation.new` only prepares
navigation. Workspace side-chat creation now explicitly requests `create_record`
and saves the empty record through ConversationLifecycle before storing its
reference in Workspace Layout; ordinary New chat retains its previous behavior.
This contract correction has not been exercised with a live model.
