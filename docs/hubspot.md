# HubSpot remote CRM MCP connector

Vellum uses HubSpot's official remote CRM MCP server at
`https://mcp.hubspot.com`. This is separate from HubSpot's local developer MCP
server. Public metadata pins the resource to that same origin, authorization to
`/oauth/authorize/user`, token exchange to `/oauth/v3/token`, client authentication
to `client_secret_post`, and PKCE to S256. No dynamic client registration endpoint
or fixed scopes are advertised. HubSpot determines permissions during installation.

## App setup and sign-in

In HubSpot, open Development → MCP Connectors (older interfaces may say MCP Auth
Apps), create a connector named Vellum and register this exact redirect URL:
`http://localhost:8000/api/plugins/hubspot/oauth/callback`.
Use the literal `localhost` hostname: HubSpot documents its HTTP redirect
exception for localhost, while other hosts require HTTPS. Do not substitute
`127.0.0.1` for this provider's callback.

Enter its client ID and secret into Vellum → Plugins → HubSpot. The guarded,
loopback-only credential adapter validates and stages them for ten minutes. Only
an opaque reference enters `hubspot.connection.configure`; the UI must confirm
that exact setup before it is saved to the existing OS credential store. Secrets
are cleared from the form after staging and discarded when a review is cancelled
or the component unmounts. They never enter chat, App Action arguments/history,
plugin manifests or `.env`. Validation errors do not echo input values.

After setup, choose Sign in with HubSpot, select the intended account and review
access. OAuth uses the existing state, PKCE, one-use callback, token refresh and
popup return lifecycle. Readiness requires authenticated tool-catalog discovery.
Verification does not fetch CRM records or invent a verified person identity.
Replacing app credentials requires disconnecting any existing account grant.
Disconnect removes the local grant while retaining app setup for reconnection.
Failed replacement authorization preserves the previous saved connection.

This local installation requires app credentials configured by its owner. A
distributed product that offers sign-in without per-install app setup needs an
appropriate confidential-client authorization service; do not embed a shared
client secret in the desktop binary or source repository.

## Tools and changes

PluginRegistry, ToolRegistry, PluginMcpRuntime and App Actions remain the canonical
owners. The complete live catalog retains original tool descriptions and schemas;
the main agent discovers it through tool search and loads schemas on demand.
Available tools can cover CRM records and activities, marketing/content assets,
analytics, conversations, schemas and account information. Account permissions,
subscription, enabled features and HubSpot's current published catalog determine
actual coverage. This does not promise every HubSpot REST API endpoint.

Writes use exact-input/account/grant/schema-bound operation reviews, existing MCP
approvals, privacy checks and audit receipts. Management and mutation tools remain
reviewed even if incorrectly marked read-only. Some HubSpot tools have provider
guidance or extra confirmation steps; those requirements are not skipped or
auto-approved. Ambiguous write results are never automatically replayed. Mixed
read/write tools take the reviewed path conservatively. Extra widgets and MCP
elicitations remain subject to host support.

The directory, tool list, connection panel and operation review reuse the existing
real HubSpot logo. The original Vellum window receives completion via local status
polling and exact-origin messages. Electron needs a full restart for the updated
OAuth launch allowlist.

Sources: [official setup and tool coverage](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/integrate-with-the-remote-hubspot-mcp-server),
[HTTP localhost redirect exception](https://developers.hubspot.com/changelog/2018-03-05-oauth2-redirect-uri-served-over-http-localhost),
[remote CRM MCP overview](https://developers.hubspot.com/docs/build-with-ai/remote-mcp-server),
[protected resource](https://mcp.hubspot.com/.well-known/oauth-protected-resource),
[authorization metadata](https://mcp.hubspot.com/.well-known/oauth-authorization-server).
