# Firecrawl and Apify connections

Each user connects their own provider account in Plugins. OAuth is the primary
action and uses public-client registration, S256 PKCE and fixed local callbacks.
No Vellum operator key or client secret is bundled for other users.

The optional **Use configured API credential** action is shown only when that
device already has the corresponding operator credential. It verifies access
and the full selected MCP catalog before saving a local OS credential record.
The model never receives the credential value. Replacing this connection with
OAuth requires provider consent; failed or cancelled replacement preserves the
previous grant. Disconnect does not silently reactivate the environment key.

## Firecrawl

Official hosted endpoint: `https://mcp.firecrawl.dev/v2/mcp-oauth`.
Resource indicators must use that exact URL. Authorization uses
`https://www.firecrawl.dev/api/oauth/authorize`; scopes are `firecrawl:global`
and `offline_access`. The callback is
`http://127.0.0.1:8000/api/plugins/firecrawl/oauth/callback`.

The connection discovers the complete tool list exposed to the selected team.
It includes scraping, mapping, search, structured extraction through scrape,
crawls and job status, parsing, remote interaction, monitors, research, usage,
and Alexandria discovery where the provider makes them available. The live
catalog is authoritative and is not a promise of every Firecrawl REST endpoint.

Team access is checked using the read-only `firecrawl_credit_usage` MCP tool.
Its billing data is not retained. Firecrawl MCP does not expose a user profile,
so the UI labels the authorized team rather than inventing a person or email.
Reviews bind the opaque verified grant revision; `identity_verified=false`
distinguishes team access from a verified personal profile.

The existing `web_extract` and extraction-provider paths reuse the saved hosted
connection once managed. They no longer launch `npx` for each operation. The
legacy operator configuration remains for installations that have not opted
into managed connections. Old `extract` requests become the published scrape
operation with JSON format; unpublished `firecrawl_extract` is not invented.
Remote browser interactions require an exact-input review.

## Apify

The official server is `https://mcp.apify.com`. Vellum selects the complete
documented platform categories: actors, docs, runs, storage, tasks and schedules,
plus the provider's report operation and its two bundled web Actors when those
are published. The endpoint opts out of provider telemetry using its supported
`telemetry-enabled=false` query parameter. Catalog access still follows Apify's
current account permissions and published surface.

OAuth uses `https://console.apify.com/authorize/oauth`, the
`full_api_access` scope and callback
`http://127.0.0.1:8000/api/plugins/apify/oauth/callback`.
The current user is verified with `GET https://api.apify.com/v2/users/me`.

Actors are discovered by search, inspected with their real schemas and pricing,
then launched through `call-actor`. Vellum does not load thousands of Actor
schemas into the first prompt. Direct Actor tools and `call-actor` require
review even if the provider annotates them as reads. Run limits and charge caps
remain exact published inputs; they are not silently discarded.

A run acknowledgement is not its output. Pending runs remain pending; use the
run-status and storage tools with the returned identifiers. Dataset reads support
provider pagination and filtering. Task publication and schedule changes use the
same exact-input review and receipt flow. The older Amazon entry now stages a
reviewed Actor call. Managed connections cannot use the unreviewed legacy Actor
runner; the old YouTube read fallback does not launch Actors behind this boundary.

## Shared ownership

`WebMcpConnection` extends the existing `OfficialMcpOAuthService` and bounded OS
credential record. Provider records use `vellum.plugins.firecrawl` and
`vellum.plugins.apify`. Refreshes serialize per grant and rejected refresh tokens
require reconnection rather than a retry loop. Public client registration is
retained for reconnection. Tokens are not written to `.env` by these flows.

`PluginMcpRuntime` continues to own endpoint resolution, transport, privacy,
approval storage and auditing. Credentials are pinned to the exact official
endpoint. `ToolRegistry` and deferred tool search expose catalog summaries,
individual schemas and native wrappers. No specialist agents are invented.

Each provider has typed status, catalog and read contracts. Connection controls
dispatch its `.connection.*` App Actions; writes use `.mcp.execute`. Reviews bind
the account/grant, arguments and schema. Ambiguous write failures are not replayed.
The original schemas, descriptions, read/review state and bundled official icons
appear consistently in the directory, tool list and operation review.

Official sources:
- https://docs.firecrawl.dev/mcp-server
- https://docs.firecrawl.dev/mcp-server/tools
- https://www.firecrawl.dev/.well-known/oauth-authorization-server
- https://mcp.firecrawl.dev/.well-known/oauth-protected-resource/v2/mcp-oauth
- https://docs.apify.com/mcp
- https://docs.apify.com/api/v2/users-me-get
- https://mcp.apify.com/.well-known/oauth-authorization-server
- https://mcp.apify.com/.well-known/oauth-protected-resource

Bundled logo sources:
- https://www.firecrawl.dev/favicon.ico
- https://apify.com/favicon.ico
