# Composer input and suggestion menus

Implemented in the canonical `Vellum Default Re-designed.html` Composer through
`composer-entry.js`, `composer-editor.js` and `composer-providers.js`. The existing
parent owns the draft; there is no second draft store, plugin registry or send
endpoint. The editor factory uses the calling React runtime, allowing the legacy
web entry and compiled desktop entry to share the editor implementation.

## Behaviour

- ProseMirror tracks the active `/` or `@` token at the caret, including its
  replacement range. Selection in the middle of a draft preserves the suffix.
  Email addresses, URLs and code spans/fences do not open unrelated menus.
- Commands match labels, IDs, descriptions and aliases. References are transient
  projections of existing library items, chats, projects, Vellum browser tabs,
  apps, skills and agents. Scopes such as `@tabs:` narrow the provider set.
- Portals escape the input's clipping area. The menu matches the input box's full
  width, aligns with its edge, flips above/below as space permits, and remains
  bounded by the viewport/dialog. ResizeObserver watches the containing elements,
  including cases where a centered input moves without changing its own width.
- Catalog refreshes preserve selection by identity. Arrow navigation reaches the
  final result and clamps there. Manual wheel/trackpad scrolling does not trigger
  selected-row recentering. Only keyboard/query navigation reveals a row.
- Both menus reuse `SharedRowBackground`. Its additive `revealActive` and
  `hoverEnabled` options let the composer own scrolling and keyboard focus;
  existing consumers retain their default behaviour.
- Mentions are atomic inline references with no pill border/background. App marks
  come from the existing connector icon resolver in local-only mode, with
  connector colours and light-theme variants. Skills use a cube icon. Slash skill
  selection also inserts a skill reference and waits for Send.
- The memory toggle is removed from the input toolbar. Memory settings and the
  existing conversation policy remain in their current owners.
- Dictation appends, multiline input, file paste, undo, IME composition and Send
  remain connected to the existing Composer callbacks. Native browser visibility
  accounts for a menu overlapping its guest bounds, using its existing mount
  queue and temporary still mechanism rather than another rendering transport.

## Reference boundary

`ConversationAttachment.reference` contains a bounded typed kind, ID, label and
optional HTTP(S) URL. Credentials in URL userinfo are rejected; known credential
query keys and fragments are stripped server-side. Selecting an identity does
not fetch a chat body, browser page or skill package, execute a tool, or grant
permission. Prepared file references retain the existing attachment content and
disclosure flags. Other references carry metadata only.

The API builds a local attachment-text envelope stating that the metadata is
untrusted data and the referenced contents have not been fetched. It reaches the
existing DisclosureBroker/external-model boundary or existing on-device adapter.
The existing agent, tool and skill policies remain authoritative. References are
editor state until sent; this does not add durable unsent rich-document storage.

## Verification actually performed

`scripts/verify-composer.py`: **27 checks passed** using a disposable muted
headless Brave session, fake catalogs/drafts, blocked networking and explicitly
fulfilled bundled logo files. It exercises the served editor, providers, shared
background, actual Composer callbacks, attachment model and the API's envelope
builder. It covers full-width layout, parent resizing, narrow viewports,
keyboard traversal/catalog refresh, wheel scrolling in both menus, multiple
coloured connectors, skill icon/insertion, references and prepared files,
deletion/undo, stale asynchronous results, IME, dictation-style append and paste.

`scripts/verify-workspace-split.py --built`: **18 layout cases passed**, including
fake native-bridge hide/restore for composer popup overlap, maximum one concurrent
mount request, no hide during divider dragging, and zero page errors. This is
not a physical Windows WebContentsView acceptance test.

Desktop UI build passed. Whitespace checks passed for the changed tracked source
files. The Impeccable CLI scan could not complete: it returned ENOENT for the
existing composer-editor.js file with relative/absolute paths and outside the
restricted runner. This is a scanner failure, not a clean-scan result. No full frontend
or backend suites, signed-in browser automation, desktop interaction or CI runs
were performed.

## Existing findings and limits

- Action Parity has the same seven unrelated findings recorded before this work:
  Settings/Music query-string source registration (four messages), Plugin
  Workspace and Automation Notifications handler drift, and the sidebar pin
  probe. Only reviewed composer/shared-background fingerprints were updated.
- Frontend dependency audit reports two moderate and one high finding in the
  existing Vite/Vitest toolchain; none names a new ProseMirror package. No audit
  suppression or unrelated dependency upgrade was made.
- The build still reports the pre-existing empty selector in
  `components/plugin-workspace.css:180`, classic-script bundling notices and the
  existing chunk-size warning. It completed successfully.
- The rebuilt desktop app was launched after no Vellum/Electron process or UI
  listener was found. The desktop entry returned HTTP 200 and named the freshly
  built JavaScript asset; the startup log confirmed the workspace document loaded
  and backend became ready. The running backend OpenAPI schema contains the
  reference ownership fields. This checks service/build identity, not attended
  UI appearance, real connections or React 18 web behaviour.

The design follows the user's supplied inspection findings for caret detection,
providers, portals and keyboard/editor focus. It does not copy the inspected
application's bundle or claim equivalence with its unverified internal features.


## Categorized connector context follow-up

The canonical plugin registry projects versioned typed relationships and
provenance through `contracts/plugin_catalog.py`. Source adapters and declarative
archive import retain explicit canonical app, remote plugin and marketplace/source
identities. Native connector manifests register an app identity from their
explicit type; configured standalone MCP records do not become plugin packages.
Configured does not imply connected, and neither state is inferred from a name.

Composer providers consume those existing records, retain child ownership and
suppress canonical app aliases in unscoped context search. Category browsing can
still select a package or MCP server. `/` groups registered commands/workflows
and offers scoped category browsing when sections are long. `@` starts with a
category index and presents categorized search results. Sites is omitted.
The existing Plugins/Apps/MCPs/Skills settings tabs use the same projection;
no technical metadata panel was introduced.

The floating menu uses a 20px outer radius, 4px inset and 16px option/shared
highlight radius, icon/text/detail columns and quiet non-selectable headings.
Optional corner-shape support is progressive enhancement; measured radii passed.
The isolated checks now also cover real temporary registry/source records,
disabled state, archive-import link preservation, canonical duplicate suppression,
scoped owned references, slash category browsing, and the actual settings-tab
component over fake data. No live connector execution, installation in the user's
workspace, browser automation against the open app or full test suite was run.
