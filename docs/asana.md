# Asana V2 MCP connector

Vellum connects directly to `https://mcp.asana.com/v2/mcp`, the standard official
V2 server. The deprecated V1 SSE endpoint is not used. The separate licensed
Command MCP server is not selected.

## App setup

In [Asana's developer console](https://app.asana.com/0/my-apps), create Vellum and
choose **Asana MCP**. External MCP brings another server into Asana's features.
Register the exact redirect `http://localhost:8000/api/plugins/asana/oauth/callback`.
Under Manage distribution, allow the intended workspaces and save. A specific
workspace distribution with no workspaces selected cannot authorize users.

Refresh Vellum → Plugins → Asana. Enter the app's client ID and secret, then
Review app setup → Save app setup. The guarded loopback adapter stages credentials
for ten minutes. Only an opaque reference enters the confirmed UI-only App Action.
The form masks the secret and clears it after staging. Cancel/unmount discards the
staged reference. Secrets never enter chat, action arguments/history, manifests,
source or `.env`. The existing OS credential store holds app credentials and
per-user tokens, without plaintext fallback.

Choose Sign in with Asana and review your intended account's access. Readiness
requires authenticated catalog discovery. Completion closes the OAuth child and
resumes the original app. Electron needs a full restart for the added allowlist.
Changing app credentials requires disconnecting an existing grant first.

This is local owner-managed app setup. A public Vellum distribution with shared
confidential-client credentials needs suitable authorization hosting and Asana
distribution approval. Do not embed a shared secret in the desktop binary.
Each user must grant their own account access.

## OAuth and provider metadata

No dynamic client registration is supported. Current protected-resource metadata
at `https://mcp.asana.com/.well-known/oauth-protected-resource/v2` advertises
resource `https://mcp.asana.com/v2/mcp` and authorization server
`https://app.asana.com`. The unauthenticated MCP challenge points to this working
metadata path; the guide's differently positioned discovery URL returned 404.
Older examples use resource `/v2`; this connector uses the current advertised
`/v2/mcp`.

Authorization and token exchange are pinned to `/-/oauth_authorize` and
`/-/oauth_token` on `https://app.asana.com`, using client_secret_post, S256 PKCE,
a one-use state-bound callback and the exact redirect. Explicit scope is omitted
as the V2 troubleshooting guide recommends. Access follows user permissions and
app distribution. MCP credentials are not used with ordinary Asana REST APIs.

The shared OAuth owner serializes refresh. Renewal without a replacement refresh
token retains the saved one. Failed/cancelled replacement preserves the prior
grant. Disconnect removes local authorization, rotates its revision and retains
app setup for reconnection.

## Tools and reviews

PluginRegistry, ToolRegistry, PluginMcpRuntime and App Actions retain ownership.
The complete live catalog preserves published descriptions and schemas. Tool
search discovers compact wrappers and loads schemas on demand. No Asana
specialist is required. Directory, tool list and review use the real Asana SVG.

Coverage means operations published by the standard V2 server for the actual
grant, not every REST endpoint or separate Command tools. User permissions and
workspace policy still apply. Catalog verification reads no private task content
and does not claim a verified person identity.

Writes retain exact-input/account/grant/schema-bound reviews, existing MCP
approvals, privacy validation and audit receipts. Mutation-name tools remain
reviewed even if misannotated read-only. Unknown write outcomes are not replayed.
Extra provider widgets and elicitations remain subject to host support.

Sources: [integration](https://developers.asana.com/docs/integrating-with-asanas-mcp-server),
[V2 client setup](https://developers.asana.com/docs/connecting-mcp-clients-to-asanas-v2-server),
[OAuth](https://developers.asana.com/docs/oauth),
[resource metadata](https://mcp.asana.com/.well-known/oauth-protected-resource/v2),
[authorization metadata](https://app.asana.com/.well-known/oauth-authorization-server).
