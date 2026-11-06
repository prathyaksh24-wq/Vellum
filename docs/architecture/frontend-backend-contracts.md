# Vellum Frontend/Backend Contract Boundary

Vellum's production frontend is `frontend/ui/Vellum Default Re-designed.html`.
The UI must not call backend endpoints directly from view logic. Backend access
belongs in `frontend/ui/api/*.js`, and backend routes must publish stable,
versioned contracts.

## Contract Discovery

The frontend discovers available backend surfaces through:

```text
GET /api/capabilities
```

The response is versioned with `api_version: "v1"` and `contract_version: 1`.
It declares the canonical frontend entry, supported feature surfaces, endpoint
paths, plugin ownership, and supported chat stream events.

## Integration Rules

The `accounts` capability declares Google/GitHub and hosted email identity transport.
`GET /api/accounts/status` supplies provider readiness and saved identities to
`api/accounts.js`; views never receive provider tokens. Interactive sign-in,
selection, logout, local continuation and account removal have a documented App Action deferral and stricter
local-Origin/client guards. These identities share the existing local workspace;
they are not a hosted API authentication boundary. See `docs/accounts.md`.
Sign-in accepts a validated local `return_url` and `open_browser` preference.
Provider and flow contracts expose `method` (`redirect` or legacy `device`).
Callbacks return HTTP 303 to the captured UI URL after successful verification.
`logged_out` in account status prevents stale local-use preferences bypassing
the sign-in screen; `/logout` preserves saved identities and `/continue-local`
clears that flag after an explicit local-use choice.
The welcome UI calls that choice **Continue as guest**. Email signup/sign-in use
typed `/email/sign-up` and `/email/sign-in` requests; passwords use `SecretStr`
and validation errors are redacted at the account router. Supabase Auth owns
password verification and confirmed hosted user IDs. Status exposes
`email_auth_available` and a safe unavailable reason, without service keys.
Verification uses `/callback/email` and pending S256 PKCE state. Only identity
metadata is retained locally, and public API responses never include hosted
access/refresh tokens. Signed-in settings and profile menus do not offer signup;
one Add account action remains in the profile account picker.

- UI components call `window.VellumApi.*` adapter methods, not raw `fetch`.
- Backend route handlers return typed Pydantic contracts or dictionaries built
  from contract modules under `backend/agent/contracts`.
- Plugin-owned features, including Spotify, Hermes skills, and the memory
  orchestrator, are exposed as capabilities rather than hardcoded UI assumptions.
- Breaking response-shape changes require a new contract version.
- Experimental features must be hidden or disabled from capability discovery
  until the backend route and frontend adapter are both ready.

## Adaptive UI contract

Adaptive UI extends the Workspace Layout owner and its existing
`vellum-workspace-layout-v1` device-local record. The App Action context carries
the current layout, adaptive rule state, and active project, agent, and window
identifiers. UI-originated presentation changes count as learning signals only
when the control explicitly sets `adaptive_learning_signal`; responsive layout
changes and other programmatic UI effects do not teach a preference. Submitted
NLP presentation actions can also contribute signals.

`ui.adaptive.rule.*` actions create, list, explain, enable/disable, remove, and
suppress rules. `ui.adaptive.apply` revalidates context and the reversible
presentation allowlist on the backend, returns a normal Workspace Layout
receipt, and offers Undo. The first automatic receipt includes the rule explanation; Undo
suppresses that preference. Rules never authorize privacy, data, plugin, or
external actions. Session-only presentation overrides are not learned or
overridden by automatic rules. Rule state is not a separate backend database or
cloud memory.

Appearance no longer renders the workspace layout or learned-rule editor. The
existing App Actions and chat commands still own these changes. Routine
successful navigation and visibility receipts apply normally without success
toasts, including automatic layout rules during page changes. Errors and
confirmations remain visible; rule explanations remain in their receipts and
the existing chat commands. Device settings accept `background: "next"` and
resolve it against the current device snapshot to another registered background
before producing the usual revision-checked patch.

## Natural settings and response preferences

`settings.device.update` remains the device settings writer. Its revisioned
snapshot includes the current and previous background, saved profile names,
and Personalization. Profile editing, the Custom Instructions dialog and chat
commands all dispatch that action. `settings.device.inspect` exposes actual
device values, including background history; a generic previous-background
follow-up is resolved only when the preceding request concerned backgrounds.

The main model has a directly visible `app_action` tool over the same catalog,
dispatcher, confirmations and receipts. It discovers and inspects typed schemas
before submitting changes. Failed argument validation returns the schema for a
retry. A final settings completion claim is replaced with actual failed or
pending receipt messages if the requested write was not applied. Model-driven
actions emit the same `app.action.requested` and `app.action.receipt` stream
events as parsed commands; nonstream chat responses include `action_receipts`.
Action turns retain both submitted text and assistant results in the chat.

`model.select` accepts a provider. An available configured model is selected for
the originating chat. Otherwise the existing master-thread state records the
pending provider and the receipt opens secure key entry. After the ordinary
credential confirmation and save, the settings service refreshes the canonical
provider registry and resumes that pending selection. The completion patch names
its originating conversation explicitly, including when a different chat is
currently open. Secret values never pass through the model action tool.

Personalization is projected from the submitted device snapshot into a scoped
response context; it is not another persistent preference store. Style, warmth,
enthusiasm, formatting, emojis, custom instructions and profile context reach
main and specialist prompts. Fast answers omit identity/memory context for
general questions. Recording references and automatic web/connector searches
are restricted by the shared tool policy; explicit searches retain their normal
permissions. The Voice toggle gates the existing composer entry. Voice uploads optionally
include typed Personalization for the existing STT/chat/TTS route. Canvas and
Advanced voice remain visibly unavailable in this branch because their editors
or hands-free runtime are separate work; enabling them reports unavailable.

## Required Verification

Run these checks before treating a frontend/backend boundary change as ready:

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_api.py -k capabilities -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

## Local dictation

The voice capability adds dictation status, prepare, transcribe, preferences,
history and a per-entry recording download. Dictation is an editable text input
transport and never submits a chat turn. The voice adapter owns discovery and
WAV transport; the composer and Settings → Voice → Dictation use it. Persisted
preferences use dictation.settings.update; audio/text deletion uses confirmed
dictation.history.delete. See docs/voice.md for local retention and setup.


### Measured workspace panes and sidebar sizing

The existing Workspace Layout surface contract adds optional integer
`sidebar.properties.width` (200–400 CSS pixels), configured through
`ui.surface.configure`. Absent or invalid frontend snapshots render the 260px
default; the backend rejects invalid writes. Browser visibility does not change
that width. `right-panel.properties.chat_ratio` remains the persisted split
preference. `BrowserSplitView` measures the region after navigation, derives
bounded transient pixel geometry and projects split/drawer mode without writing
responsive constraints back as preferences. Drag gestures commit once; failed
receipts roll back the transient preview. Native browser bounds requests are
coalesced and serialized across effect restarts, retaining the existing bridge.


### Structured composer references

`ConversationAttachment` adds optional `reference` metadata: a typed reference
kind, bounded ID/label and optional HTTP(S) URL. URL credentials are rejected;
known credential query keys and fragments are removed server-side. The composer
inserts an atomic reference and sends it only through the existing attachment
list when the user sends the message. Selecting a reference neither fetches its
contents nor runs an integration or skill. Prepared library files retain their
original payload/disclosure flags. Other references carry identity metadata only.
The API converts that validated metadata to an explicitly untrusted local text
attachment envelope, using the existing DisclosureBroker or on-device adapter.
No new endpoint, permission grant, catalog owner or durable draft store is added.


The existing plugin catalog also publishes typed `relationships` and `provenance`
subrecords from PluginRegistry. Components name their app/MCP/skill identity and
owner, with separate enabled/configured/connected states. Marketplace and source
identifiers are declared provenance, not authorization or trust. The existing
settings tabs and composer providers project these same records. Composer
references add `plugin` and `mcp` kinds plus bounded `owner_plugin_id` and
`component_id`, preserving a scoped child identity through the existing attachment
path. These fields grant no access and trigger no connector execution.


### Removal of standalone coding mode

Vellum has one main chat/workspace interface. The standalone coding page, its
`/api/coding/*` router, session engine, Codex/Claude adapters and session-bound
PR actions have been removed. Their App Action IDs are absent from the catalog;
old-client dispatch returns `unavailable`. No coding launch receipt handler is
loaded by the main shell. Coding requests follow the ordinary main-chat path.

The main GitHub connector and terminal retain their existing owners and
permissions. Existing coding-session databases and user worktrees remain on disk
and are not opened or migrated. Finishing the current Vellum workspace takes
priority; selecting and integrating a future coding harness is separate work.


## Retained workspace views

The served chat entry uses `components/workspace-controller.jsx` and
`components/workspace-content.jsx`. New tab opens a content pane beside chat with
address entry and Browser, Files/previews, Side chat and Terminal choices. Split
view has a content strip; full view includes the main conversation as its first
tab. The native title bar does not own these controls.

Workspace Layout remains the presentation owner: `ui.surface.configure` accepts
right-panel `content` (`files`, `browser`, `workspace`), `layout` (`split`, `full`),
`chat_ratio`, bounded `items` and `active_item`. Items are validated presentation
references to launcher, chat, files or terminal owners, capped at twelve. The
independent `chat-details` surface owns visibility and boolean `pinned`. It projects
structured task resources and reported progress without generating or compacting history.

Browser tabs continue through `browser.session.control`. Side chats materialize
a canonical record through `conversation.new` with `create_record:true`; without
that option the action retains ordinary navigation-only behavior. Sending,
streaming, cancellation, model selection and persistence use existing conversation
owners. HTML file previews are sandboxed with scripts disabled.

`workspace-entry.js` imports the existing frontend terminal owner. Backend
capabilities publish profile discovery and the dedicated loopback-origin-checked
terminal WebSocket. Windows keeps its installed profiles and WinPTY; macOS/Linux
select the configured local shell with a POSIX PTY. Direct shell input remains
explicitly outside generic App Action parity, is user-operated, and is not an
agent-command channel. Native platform execution and full interactive acceptance
remain unverified; see `docs/verification/workspace-content-2026-11-03.md`.

### Removal of standalone coding mode

Vellum has one main chat/workspace interface. The standalone coding page, its
`/api/coding/*` router, session engine, Codex/Claude adapters and session-bound
PR actions have been removed. Their App Action IDs are absent from the catalog;
old-client dispatch returns `unavailable`. No coding launch receipt handler is
loaded by the main shell. Coding requests follow the ordinary main-chat path.

The main GitHub connector and terminal retain their existing owners and
permissions. Existing coding-session databases and user worktrees remain on disk
and are not opened or migrated. Finishing the current Vellum workspace takes
priority; selecting and integrating a future coding harness is separate work.


### Task summaries and registered workspace tools

`components/workspace-resources.js` projects immutable message records into
progress, outputs, inputs, provenance/sources, side conversations, subagents,
associated schedules, browser activity and available environment information.
Absent data produces no section. Section expansion is transient UI state keyed
by conversation/section; summary visibility and pinning retain the independent
`chat-details` Workspace Layout surface. The 300px surface chooses an overlay,
shift or gutter presentation by content width; tab visibility and native guest
occlusion remain independent. The shortcut is Ctrl/Cmd+Shift+S.

The same module supplies launcher descriptors for available browser, terminal,
file, and side-chat tools. Suggested entries come from the conversation's
artifacts or generated code. Side chats use the main composer and
ConversationLifecycle with an optional validated `parent_conversation_id`.
They stay out of the conversation sidebar. Closing their tab stops pending
turns and discards the temporary record through `conversation.delete`.
The device settings action saves preview-rail position and visibility.

The desktop `workspace_files` command accepts only list/read and a bounded
relative path. The existing host checks a registered trusted top-level workspace
frame. Reads are scoped by realpath to the selected workspace; runtime/private
paths, escaping links and previews over 2 MB are rejected. This is read-only
presentation, not an agent filesystem tool or automatic prompt attachment.

BrowserStatus reports native option capabilities and the actual zoom factor.
BrowserControl exposes UI-only find/zoom/print, download acknowledgement and
native pause/resume/cancel operations through `browser.session.control`.
Electron's existing download owner supplies received/total bytes and paused
state; the backend retains approval, save location, completion and persistence.
A transfer without a known total is indeterminate. Failed/unacknowledged saved
items drive attention. Approval-pending downloads cannot be resumed through
ordinary transfer controls. Unsupported browser options are absent.
