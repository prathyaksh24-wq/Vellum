# Plugin cleanup and connector recovery — 2026-10-29

## Scope and ownership

The user requested removal of display-only apps/plugins and unwanted skills, while
retaining Matt Pocock, OpenAI, and skills used by the main agent and specialists.
They also requested working Brave Search, Context7 and Linear connections. Changes
extend PluginRegistry, its existing source adapters, SkillMutationCoordinator,
PluginMcpRuntime, KeyringRecordStore and App Actions. The follow-up publication was
explicitly requested after merged PR #233. Its isolated branch starts at current
main `db399f5`, which also includes merged PR #234's backgrounds.

Default Codex-cache discovery now imports only the reviewed OpenAI Developers
instruction bundle. Its host app/MCP references are excluded; these declarations
do not implement a Vellum connection. Matt Pocock's named skill source is retained.
Native Vellum connectors and personal declarative plugins are preserved. Nothing
in the user's Codex installation was edited or deleted.

The running catalog reports 38 entries (35 packages/bundles plus three configured
service descriptors) and zero Apps entries. The skill registry contains 32 unique
names: 16 Matt Pocock, six OpenAI Developers and ten explicit agent dependencies.
The former imported Product Design `research` collision no longer hides Matt's
skill. Skill availability is distinct from observed use: the usage-event table
was empty and the legacy counters referred to two names absent from the catalog.
No historical-use claim is made. The hub lock has no provenance records, so an
OpenClaw origin cannot be established from this checkout.

## Retained runtime dependencies

| Profile | Skill names |
| --- | --- |
| BooksAgent | book-to-skill |
| BrowserAgent | browser-context |
| CalendarAgent | calendar-context |
| DiscordAgent | discord-context |
| MemoryAgent | skill-retention-memory-v1 |
| MusicAgent | spotify |
| SportsAgent | skill-route-sports-agent-v1, skill-sports-memory-v1 |
| XAgent | x-account |
| YoutubeAgent | skill-youtube-transcript-memory-v1 |

Ten unbound or superseded local packages were archived through the canonical
mutation coordinator, with reviewed receipts and recoverable package directories.
This is local runtime state, not deletion of the Books library or external skill
source files. The main agent retains the requested procedural bundles and its
native tools/tool-search descriptions; old tool-guide packages are not needed to
enable those capabilities.

The PR does not publish the device's archives, receipts, databases, configuration
or package state. `backend/scripts/skills_ops.py cleanup` provides a read-only plan
for the nine known legacy tool guides; `--apply` performs recoverable archival via
the existing mutation coordinator. Every configured profile dependency is protected.
Additional custom-package removal requires explicitly naming it with `--archive`.
The 32-skill count above describes the user's actual development installation,
including its installed bundles and local choices, not every fresh installation.

## Connections

Brave Search now has a real portable manifest, guarded local key staging, typed
App Actions, OS storage and a pinned official stdio MCP command. Its complete
published catalog remains deferred. Native web_search shares the saved key and
the existing provider-selection policy. The user chose to add a key later; no
Brave catalog/search success is claimed and no npm server was launched.

Context7's existing key worked against the provider; its old configuration-only
entry lacked usable Vellum setup. The corrected connection was verified through
`context7.connection.use_configured`, and both `resolve-library-id` and
`query-docs` were discovered. A public React documentation resolution then
succeeded through Vellum's PluginMcpRuntime. Only result metadata was reported.
The official Context7 logo is bundled locally.

Linear's saved grant was expired. The SDK storage adapter did not restore its
in-memory expiration deadline. Verification could overwrite rotated tokens, and
the legacy credential record was close to Windows' per-entry limit. These paths
now restore expiry, distinguish refresh from replacement grants, preserve current
credentials, and use the existing bounded atomic credential store. Terminal
background authorization failures expose reconnect_required without deleting
the previous grant.

The redesigned Linear dialog had also omitted the old provider continuation link
and called cancellation through a helper that discarded arguments. Sign-in now
reserves a browser popup synchronously, validates its provider destination, offers
explicit continuation, and cancels the exact owner flow. Browser popup returns
use escaped HTML data with a nonce CSP, focus the original app and close. Electron
uses its existing isolated authorization child with the exact Linear local route
and status header. The user completed the corrected sign-in flow; live status
reported connected/ready with 69 published tools, and catalog retrieval succeeded.

## Verification and limits

No local test suite or build was run. Regression sources were added for source
filtering, bounded credential storage, refresh preservation, key staging and
replacement, endpoint binding, popup opening/fallback/cancellation and safe return
HTML. Changed Python, JS/JSX and desktop files were statically parsed. Live checks
verified clean catalog metadata, complete agent skill references, Context7's
canonical runtime read and Linear's user-authorized connection/catalog.

The development checkout's overall inventory identified unrelated working-tree
changes in Books, Music, YouTube and automation notifications. Those changes are
excluded from this PR. On the isolated publication branch, the full static served
source/Action Parity inventory validation returned no errors. Main's credential
binding and deferred-discovery assertions are preserved. A broader App Action catalog
inspection timed out, while the selected
Context7 App Action executed successfully. These are not reported as passing
full-suite or end-to-end checks.

Brave account authorization/search, attended Electron behavior, future token
expiration and full chat-to-provider scenarios remain separate verification gaps.
The API and frontend were left running. Restart Electron for native-host changes.
