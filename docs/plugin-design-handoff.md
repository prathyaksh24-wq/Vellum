# Plugin design handoff integration

The visual reference is the user's `vellum-handoff.zip`, SHA-256
`acb27baa01e38693a4b94acebafe26373d817e0fb29a236975a6bc8819823dec`.
Its 25 standalone designs and React prototype were inspected as design inputs.
The archive's generators, package installation and test scripts were not run.

## Scope

`components/plugin-workspace.jsx` replaces the plugin directory and the Plugins
content inside Settings. Vellum retains its existing application rail, title bar,
Settings navigation, appearance, notifications and other pages. The archive's
mock application shell is not mounted. The directory retains the reference's
Customize navigation; Settings uses Vellum's existing Settings sidebar.

`plugin-workspace.css` scopes the supplied base and prototype styles to `.vplug`.
Typography, tiles, lists, spacing, pills and dialog geometry are retained.
Following the user's appearance request, colors and translucent surfaces use
Vellum's existing theme tokens and reveal its one shared background renderer.
Settings and Music also use that selected appearance. Additional rules constrain
real descriptions and long Markdown. `plugin-design-assets.js` contains the supplied
icons, logos, collection ordering and example prompts. It excludes mock accounts,
installation state, tool catalogs, invented skills and placeholder factual copy.
Existing real Vellum logos cover providers absent from the archive.

The supplied Iconify/Simple Icons assets retain their upstream brand provenance;
no brand artwork was generated. Asset names and visible identity remain those of
their providers. This integration does not assert trademark or redistribution
approval. Font declarations match the handoff's Inter and JetBrains Mono.

## Screen ownership

| Reference screens | Production presentation |
| --- | --- |
| Main, Popular | Directory sections, category list, search, Public/Personal and row menus |
| Detail | Real plugin identity, example prompts, included content and source information |
| Install, Uninstalling | Reviewed installation and actual pending/applied lifecycle state; no simulated progress timer |
| Manage, Uninstall | Connection management and confirmed local installation removal |
| NewPlugin | Plugin archive picker and canonical declarative import |
| AddMarketplace, AddMcp | Source and connection forms through typed App Actions |
| SkillsDirPersonal, SkillsDirSystem | Resolved skill catalog with source/ownership grouping |
| SettingsPlugins | Installed plugins and receipt-backed enablement |
| SettingsLinear, SettingsLinearMenu, SettingsNetlify, SettingsPluginCreator | Shared plugin settings, truthful connection state, account actions and About data |
| AppsList, AppModal, AppModalExpanded | Actual declared apps and grouped published read/write tool metadata |
| McpList | Actual standalone and plugin-owned servers; provider authentication and catalog inspection |
| SkillsList, SkillsMenu | Resolved skills, source labels, ownership-aware switches and actions |
| SkillModal, SettingsSkillFile | Real SKILL.md reader, metadata, source/preview, copy and native file opening |

Real counts and source-owned contents replace the prototype's sample numbers.
MCP-only plugins remain MCP servers rather than being given fictional app entries.
Tool browsing is explicit; provider catalogs are fetched only when their detail
is opened. Skill catalog pagination is deferred until skills/management is opened.

## Backend and lifecycle

The parent application still owns the plugin snapshot. Reads use `api/plugins.js`.
Changes use the existing App Action dispatcher, confirmation and receipt owners.
The existing provider components expose an optional presentation callback; their
credential staging, PKCE/state checks, polling, refresh, endpoint validation,
secret redaction and disconnect confirmation remain in those owners.

`PluginRegistry` now records an additive `installed` map beside `enabled` in its
existing state file. Existing records default to installed. `plugin.install` and
`plugin.uninstall` require operation-bound confirmation. Uninstall disables the
plugin's tools and owned skill roots without deleting source files, provider
accounts or saved authorization. Required/protected installations cannot be
removed. Enablement cannot bypass an uninstalled state; explicit installation is
required. No secondary installation store or runtime was added.

Disconnect remains a separate provider operation. The uninstall dialog's combined
disconnect option is unavailable until a coordinated provider/installation action
exists. It does not claim to pause scheduled tasks or delete another app's files.

## Categories

The canonical catalog classifies plugins by purpose, independently of MCP, CLI or
API transport. Asana, Airtable, HubSpot and ClickUp belong to **CRM & Communication**,
along with Slack, Discord, Gmail and Contacts. Calendar, Drive, Notion and Linear
belong to Productivity. Other groups include Developer Tools, Web & Research,
Creativity, Data & Analytics, Memory & Knowledge, Food & Experiences and Media &
Entertainment. Source identity and transport stay unchanged.

Each plugin has one primary category. Popular and New & Noteworthy are curated
collections over the same identities; their presence does not duplicate an
installation. Unknown custom connections retain Personal or their configured
category. Category assignment is shared by manifests and external catalog
projection, not a separate frontend-only mapping.

## Existing capability limits

- Provider grants and workspace roles control access. Per-read/write permission
  switches remain unavailable; reconnect changes provider consent.
- Existing provider owners support one account per connector on this device.
  Provider-controlled account rename and additional-account actions are not
  reported as successful local changes.
- Custom server OAuth/CIMD/DCR, tunnel provisioning, custom icon persistence and
  MCP app-widget cache clearing do not have canonical backend implementations.
  Their supplied controls explain unavailability instead of simulating success.
- Declarative archive import currently accepts ZIP up to 2 MiB. Format and size copy reflects the actual backend restriction rather than the
  prototype's unsupported 100 MB/tar promises.
- Marketplace registration currently supports public GitHub owner/repository and
  one relative skills path on its default ref. Other source/ref forms are rejected
  truthfully rather than saved only in browser state.

These limits are distinct from visual integration. No provider account content,
mail, booking, reservation or payment is required for UI verification.


## Plugin sidebar visibility

The Customize sidebar has the same panel icon control as the main sidebar.
When collapsed, a small Show plugin sidebar control remains at the content edge.
Visibility uses the registered `plugin-sidebar` surface through
`ui.surface.configure`, its applied receipt and the existing workspace-layout
storage. It restores across reloads independently of the main `sidebar` surface.
There is no new browser storage key or local optimistic visibility store. Settings
continues to use its existing navigation and does not mount a Customize sidebar.

## Catalog browsing

The directory requests metadata without resolving every provider's credentials.
`PluginMcpRuntime.connectors(resolve_credentials=False)` returns declaration
previews; credential-backed previews are explicitly deferred and cannot be used
as execution-ready connections. Actual tool calls still resolve the selected
connector through its existing endpoint binding and authorization checks.
The catalog shares one request-local registry snapshot across configuration and
presentation, avoiding repeated manifest discovery in the same request.

## Verification on 2026-10-27

- An isolated headless browser rendered the served page and exercised the actual
  `ui.surface.configure` path: hide, reload, show. The plugin sidebar remained
  hidden after reload, and the main sidebar's visibility stayed unchanged.
- The directory contains no copied prototype toolbar or outer rail. Plugin
  settings retained Vellum's Settings navigation and mounted no Customize sidebar.
- Settings displayed 124 real skills. Opening a skill loaded its actual Markdown
  source (6,547 characters in the inspected entry).
- The local catalog returned 55 plugins in 3.2 seconds after metadata browsing
  was separated from provider credential resolution. This is one observed local
  request, not a general performance guarantee.
- The served-control Action Parity inventory had no validation errors. Source
  syntax and scoped whitespace checks were also performed.
- Captures and the compact render report are under
  `.tmp/plugin-design-handoff/`; these are local verification artifacts.

No test suite or build was run. OAuth consent, provider account operations,
installation removal and external writes were not exercised during these UI
checks. The isolated browser emitted the existing Spotify EME message,
`No supported keysystem was found.`; no plugin UI page error was observed.


## Shared appearance and GitMCP follow-up

Plugin directory, details, setup dialogs and Settings now use Vellum's existing
appearance tokens and the single app background layer. This covers light scene
palettes as well as Galaxy and Particles. The Music page and its main/sidebar
surfaces likewise stop imposing an opaque dark background. Vinyl artwork, cover
art, provider logos, layout and playback handlers are retained. Settings hides
its already-inert underlying content while revealing the shared background;
closing Settings restores the existing content. No second background selection
store or renderer is introduced.

GitMCP is a portable connector under Developer Tools, replacing the synthetic MCP
configuration row by its existing stable ID. It uses the existing deferred
repo_docs adapter (all five operations), and an on-demand catalog route on the
existing plugin MCP API. The public service requires neither OAuth nor a key.
A Verify connection read shows live reachability, without inventing an account
or persisting a fictional OAuth grant. Disable/uninstall blocks both the generic
connector and the repo_docs adapter. The documented readers are classified as
reads only on the exact upstream generic endpoint; unknown tools and custom
endpoints retain the normal annotation and approval rules.

Live checks returned exactly one GitMCP catalog entry, five published tools,
a correct LangGraph repository match, and 15,818 characters of upstream public
documentation. Focused regression coverage was authored for disabled execution,
endpoint-scoped read classification, and anonymous connection UI. It was not run.


### Light-theme detail correction, 2026-10-28

Replaced the remaining fixed light prompt, status, metadata and dialog colors
with appearance-aware foregrounds. Light scene palettes use dark prompt text,
readable status/error tones, and theme-aware fallback/logo tiles. Removed the
inherited text shadow that embossed small plugin labels. Music retains readable
control icons and provider branding in light palettes.

An isolated Drifting Clouds detail render passed the targeted check: title and
prompt emphasis resolved to rgb(16, 29, 49); description, prompt text, body,
metadata labels and values resolved to rgb(38, 58, 87). Screenshots were inspected
at both the top and metadata end of the detail page, with no page errors.
Galaxy, Particles and Drifting Clouds were also captured on Plugins, Settings and
Music during implementation. Those appearance captures used the current real
catalog snapshot and an unconnected Spotify response; they do not verify Spotify
playback or account refresh. The broader sequential capture scripts encountered
startup/catalog and Settings-navigation timeouts, so they are not reported as a
passing end-to-end suite. The focused final light-detail check passed.

The restarted API exposes PublishedMcpCatalog and returns all five GitMCP tools
as reads. Frontend 5173 and backend 8000 are running. No test suite or build was
run, and no Git publication was performed.
