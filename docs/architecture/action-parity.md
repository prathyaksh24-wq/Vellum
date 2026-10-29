# Action Parity verification

Issue #176 inventories the served interface in `frontend/ui/action-parity.inventory.json`.
The inventory separates covered visual controls, non-state exemptions, and
surfaces that still need a canonical App Action. A deferral is not a claim of
parity.

The frontend contract test parses the JSX actually served by the main and
coding workspace HTML pages, including their external React components. It
locks the tag/event/handler-expression multiset for the reviewed handlers.
An added, removed, or rewired handler fails the test until its Action mapping
or narrow exemption is reviewed and the fingerprint is updated. Covered
controls also have source probes; the backend contract test checks that each
listed Action ID exists in the composed App Action catalog. This is a change
gate, not whole-program proof that every callback reaches a dispatcher. In
particular, source probes do not prove a backend receipt is applied at runtime.

Review rule: when a visual handler changes, classify the control as an App
Action, a non-committing gesture, or a specifically named deferral. Do not
refresh a fingerprint alone to make the test pass. If a deferral acquires an
Action, move it into `covered` and add a behavior test. If a new React script
is served, add it to the scanner first.

## PR #200 merge reconciliation

The merged inventory covers 74 controls. Calendar moved from the inline page
to the served `calendar-workspace.jsx`, which is now scanned. Calendar connection
and confirmed event mutations, Spotify connection/consent upgrade, playback
controls, and embedded-player session controls have canonical App Action mappings.
Backend catalog checks compose both plugin contributions; existing dispatcher,
confirmation, SDK lifecycle, and Calendar UI tests cover those boundaries.

| Changed handlers | Reviewed classification |
| --- | --- |
| Calendar component callbacks, create/update/delete and confirmation | Typed Calendar actions; source calendar identity is preserved. |
| Calendar refresh, selection, search, proposed slots and cancellation | Provider reads or staged form choices; no committed event mutation. |
| Spotify connect/reconnect, audio enable/disable and player controls | Existing connection, playback and session App Actions; reconnect can explicitly reuse the saved public client ID. |
| Plugin detail toggle | Existing `plugin.state.set` dispatch, with the selected plugin resolved before rendering. |
| X connection setup, session-cookie draft and connection badge | Existing named third-party connector deferral; typing is a draft and opening setup is transient presentation. |
| New chat | Existing `conversation.new` action with delayed navigation handling; probe updated to its complete invocation. |

This reconciliation preserves the validation limits below. Automated merge
checks do not constitute a new live provider or browser acceptance run.

## Browser validation (disposable fixture)

### Dock music controls

The dock owns the compact music presentation while SpotifyPlayer keeps the
existing controller and snapshot. The five removed and seven added inline
handlers were reviewed before updating the main-page fingerprint: native button
disclosure replaces the nested role-button/keyboard handler, close and focus
capture are temporary presentation gestures, and Agents/Open Music dismiss the
popover before their existing navigation. The compact Next shortcut was removed;
Next remains in the expanded controls with the same `spotify.playback.control`
mapping. Playback and audio-session adapters are unchanged. Component tests cover
dock containment, transport dispatch, auto-hide, outside dismissal, keyboard
focus, four dock positions, disconnection, and single-controller navigation.

The browser panel's direct page gesture now combines bounded takeover and the
original click in one `browser.session.control` action. The server checks the
displayed document identity and coordinates before changing ownership. Buffered text, special
keys and wheel input retain queue order and use the same Action; viewport resize
also uses that Action without changing agent ownership. Hide remains a Workspace
Layout presentation action, after flushing typed input. The 27 browser handlers
were reviewed under those existing mappings before updating their fingerprint.
Live frame streaming is read-only and is not an input or mutation channel.

The panel's capture-phase shortcut handler dispatches the same tab/navigation
App Actions. Address focus and Escape propagation are non-committing gestures;
Escape's remote fullscreen exit remains a checked page-key action. Both chat
and specialist Sources/Activity handlers now explicitly select the existing
`files` content mode through Workspace Layout presentation, whose existing
Activity drawer renders the selected message. This prevents a previously used
`browser` mode from reopening when Sources is clicked. The two main-page
handlers retain their canonical action mapping.

The served Vite page was checked against `backend/tests/action_parity_live_server.py`.
That fixture puts conversations, plugin enablement, and automations under a
temporary directory; it uses the real App Action planner/dispatcher, plugin
registry, automation store, and observability action adapter. Its chat answer,
agent selection, observability metrics, and scheduler availability are
synthetic. It never calls a model, launches a coding session, schedules a real
run, or touches a user profile. This is UI-to-contract validation, not a
production end-to-end claim.

To repeat the browser check, start the fixture from `backend/tests` with the
repository's `backend` directory on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = (Resolve-Path ../../backend).Path
python -m uvicorn action_parity_live_server:create_app --factory --host 127.0.0.1 --port 8018
```

In another shell, run `npm --prefix frontend run dev -- --port 5176` from the
repository root. Open
`http://127.0.0.1:5176/design-uploads/Vellum%20Default%20Re-designed.html?backend=http%3A%2F%2F127.0.0.1%3A8018`.
Stop the fixture after validation; its data directory is discarded.

| Area | Verified in the served browser | Limit |
| --- | --- | --- |
| NLP/click parity and mixed turns | “hide the sidebar” matched the click path; “hide the sidebar and tell me a joke” hid it and preserved a conversational reply. | Reply text is a fixture string, not inference. |
| Workspace Layout, persistence, reset, Undo | Sidebar hide/expand, composer size, reload persistence, Reset surfaces, and sidebar Undo worked. Ctrl+Shift+S recovered the sidebar while hidden. | Kernel protection for all eight combinations of optional surface visibility is asserted in the backend contract test. |
| Conversations | Open, pin and reload, cancel a delete confirmation, and fork a chat worked. | Message-level fork was not exercised with a persisted message; native new-window correctly reported that desktop support is required. |
| Attachments | Composer Add opened the file/recents picker. | No file was uploaded in the browser; attachment preparation/dispatch is covered by backend tests. |
| Plugins | A temporary plugin was disabled and re-enabled through `plugin.state.set`, with the card and receipt updating. | External connectors and OAuth were not exercised. |
| Observability | The empty fixture snapshot rendered; Live/Pause/Resume/Refresh changed state through App Actions. | No real model run or usage ledger was present. |
| Automations | Created a temporary task, paused it, read empty history, and confirmed its paused state after reload. | No actual scheduler or model run was started. |
| Agents | The fixture Books specialist appeared and selection returned a receipt. | Specialist inference and local profile settings were not exercised. |
| Pets | Show pet switched on/off with receipts. | Gallery installation was not exercised. |
| Adaptive UI | Rule controls and settings rendered; layout learning/Undo paths are covered by focused tests. | No learned rule existed in the fixture to click through. |
| GitHub PRs | Coding workspace showed Pull requests disabled with “Open a coding session first” while its backend was offline. | No GitHub PR was opened or created in the browser. The create-PR visual control is deferred. |

The full frontend test suite and production build are required. The selected
backend regression set includes App Actions, conversations, adaptive UI,
attachments, knowledge sources, automations, lifecycle, observability, Pets,
coding GitHub, plugin contributions, privacy, memory, and chat streaming.
Run the complete backend suite in CI; the local full backend suite was skipped
at the user's request.

## Window menus and account identity presentation

The Windows title bar forwards only the existing Vellum, Edit, View, and Window
menu identifiers through a dedicated native-frame bridge. Native caption/menu
interactions retain Electron's existing handlers; web previews have no bridge.
Theme changes and menu anchoring are transient window presentation. The account
picker remains bound to the existing local Accounts API deferral. Sorting the
active identity first and labeling other identities Saved changes presentation,
while switch, logout and removal retain their existing account owners. The
reviewed Accounts handler fingerprint is updated for its extracted row callback.

## Dictation settings

The served `dictation-settings.jsx` is included in the scanner. Saved language,
recording retention, dictionary words and shortcut chords dispatch the existing
Settings runtime's typed `dictation.settings.update`; recording/transcript
removal dispatches `dictation.history.delete` with operation-bound confirmation.
Search, language filters, paging, full-text expansion, retry, clipboard copy,
explicit local WAV export, and unsaved preference edits are narrow non-state
exemptions. The composer remains ordinary conversational transport. Its language
selector was removed and shortcut help receives the saved chord. Only these
reviewed handlers were refreshed; unrelated inventory drift is reported separately.

## GitHub connection and operation reviews

The served `github.jsx` is registered with the scanner. Sign-in/reconnect,
sign-in cancellation, verification and disconnection dispatch
`github.connection.oauth.start`, `github.connection.oauth.cancel`,
`github.connection.verify` and `github.connection.disconnect`. Disconnection
confirmation and cancellation use the existing App Action confirmation tokens;
confirmed provider changes use `github.mcp.execute` through the shared readable
review. The added main-page callback refreshes catalog presentation after a receipt.

Tool catalog browsing/refresh and filtering are read-only metadata requests and
in-view presentation. OAuth continuation and documentation links are navigation;
the server retains authorization state and validates each flow. These gestures
do not gain permission to perform provider writes. Only the reviewed main-page
and GitHub component fingerprints are updated; the backend catalog fixture now
composes GitHub's contribution as production does.

## Slack connection and operation reviews

The served `slack.jsx` participates in the same scanner. Public app registration,
sign-in/reconnect, sign-in cancellation, verification and disconnection dispatch
`slack.connection.configure`, `slack.connection.oauth.start`,
`slack.connection.oauth.cancel`, `slack.connection.verify` and
`slack.connection.disconnect`. Changing an existing registration requires explicit
disconnection first. Disconnection decisions retain the existing confirmation
tokens. Provider changes use `slack.mcp.execute` with account, workspace, grant,
schema and exact-argument binding; the shared preview uses Slack's logo.

App ID/Client ID drafts, tool filtering, manifest disclosure/copying, provider
metadata reads, OAuth continuation and documentation links are non-committing
gestures. A parent refresh callback updates catalog presentation after receipts.
The backend catalog fixture composes Slack's contribution. Only the main-page
and new Slack component handler fingerprints change in this integration.

## Hosted connector controls

Airtable, Notion, Firecrawl, Apify, SerpAPI, Exa and Tavily connection lifecycle
controls and operation reviews dispatch typed App Actions. Secret staging is
guarded UI-only transport; only an expiring reference reaches SerpAPI's connect
action. Search preference selection uses `settings.web_search.set` through the
canonical config writer. Read-only metadata, filters and OAuth polling retain
documented exemptions. All served connection sources are in the parity inventory.
