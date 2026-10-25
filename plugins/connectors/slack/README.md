# Slack

Vellum connects to Slack's official Streamable HTTP MCP server at
`https://mcp.slack.com/mcp`. The complete catalog is discovered after authorization;
individual schemas are exposed through existing tool search instead of injecting
every schema into the initial prompt. This covers what Slack publishes over MCP,
not every method in the larger Slack Web API. User scopes and workspace policies
still determine which operations succeed.

## Set up a workspace app

1. Open [Slack Apps](https://api.slack.com/apps), choose **Create New App → From an
   app manifest**, select the intended workspace and choose JSON. Paste the bundled
   `slack-app-manifest.json`, also available through Vellum's Copy app manifest button.
2. Review the manifest's user scopes and create the app. It enables the Slack MCP
   feature, public desktop PKCE and token rotation. PKCE and token rotation are
   one-way Slack app settings; use a dedicated Vellum app. No bot scopes are requested.
3. From **Basic Information → App Credentials**, copy the public App ID and Client
   ID into Vellum → Plugins → Slack → Set up your Slack app. Save the registration.
   The app secret is not needed by this public PKCE client.
4. Choose **Sign in with Slack**, select your workspace and approve the user scopes.
   If installation is restricted, a workspace admin must approve the app. Vellum
   verifies the returned user token with `auth.test` and loads the official MCP
   catalog before reporting Connected.

The callback is exactly
`http://localhost:8000/api/plugins/slack/oauth/callback`. Slack documents localhost
redirects for PKCE desktop clients. Register this URL without replacing it with
an unrelated HTTPS URL. The local backend must be available on port 8000.

Slack currently allows internal apps and Marketplace-published apps to use MCP;
unlisted distributed apps are not supported. This local workspace-app setup does
not establish a Marketplace-published Vellum integration. A future published
registration can supply one app identity to users rather than asking each to
create an internal app.

## Authorization and tools

App registration and access/refresh tokens stay in the OS credential store under
`vellum.plugins.slack`, `connection-v1`. The small root entry references bounded,
generation-specific OS entries, each below Windows Credential Manager's blob
limit. Parts are written and read back before switching the root; the preceding
generation is cleaned up after that switch. Incomplete records fail closed.
Existing single-entry registrations remain readable. They are not written to `.env`. Only public
IDs, verified identity, scope names and connection metadata cross the status API.
Token rotation happens at operation time, not during the initial model prompt.
Reconnect/cancel/expired callbacks cannot overwrite a newer saved connection.
Disconnect clears this connector's local grant and cache but retains the public
app IDs for reconnection. Revoke the app in Slack to withdraw the provider grant.

`slack_mcp_catalog` returns paged summaries; `slack_mcp_describe` loads one exact
schema. `slack_mcp_read` accepts only published read-only operations.
`slack_mcp_execute` prepares the existing App Action review. Cached native tool
wrappers preserve every published field, including pagination. Unknown tools are
rejected. Tools lacking a read-only annotation require review.

Writes bind the exact account, workspace, authorization generation, schema and
arguments. They consume the canonical MCP approval and retain receipts. Slack
errors, including an `ok: false` payload, do not produce success receipts. A
timeout never automatically replays a write. File uploads retain Slack's published
two-step upload-URL/completion protocol; exposing its tools does not itself upload
arbitrary local file bytes.

OAuth popup completion uses a fixed script reading escaped data attributes. It
posts only to the exact validated app origin, attempts to close and refocuses the
original window. Desktop auth uses the existing isolated provider window without
a preload, Node access, native bridge or device permissions.

Connection errors distinguish transport, provider HTTP status, catalog schema
validation and saving authorization. Diagnostic logs contain only fixed category
names, exception types, numeric status/error codes and storage sizes; provider
bodies, tokens and authorization URLs are not logged by these diagnostics.

Sources: [Slack MCP](https://docs.slack.dev/ai/slack-mcp-server/),
[desktop PKCE](https://docs.slack.dev/authentication/using-pkce/),
[user-token OAuth](https://docs.slack.dev/reference/methods/oauth.v2.user.access/),
[authorization metadata](https://mcp.slack.com/.well-known/oauth-authorization-server).
