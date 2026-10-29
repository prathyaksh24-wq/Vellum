# ClickUp MCP connector

Vellum connects to ClickUp's official `https://mcp.clickup.com/mcp` endpoint using
its own public OAuth client, PKCE and the existing OS credential store. The OAuth
resource is `https://mcp.clickup.com`, without `/mcp`. Authorization, token and
registration endpoints are pinned to `/oauth/authorize`, `/oauth/token` and
`/oauth/register` on that same origin. The fixed local callback is
`http://127.0.0.1:8000/api/plugins/clickup/oauth/callback`.

ClickUp's advertised grants include `authorization_code` only. Registration does
not request an unsupported refresh grant. Token responses without a refresh
token or expiry are accepted when otherwise valid; Vellum never fabricates
either value. A supplied positive finite expiry is enforced, including ClickUp's
observed 315,360,000-second (ten-year) lifetime; there is no arbitrary one-year
maximum. If authorization expires without a
refresh token, the user must reconnect. Public status never contains tokens.
Requested permissions are `read write`; granted scopes follow the token response.
Each user signs in and selects the intended workspaces through ClickUp.

Registration metadata is retained privately before validation, so correcting an
incompatible response does not silently create repeated clients. Client IDs are
treated as bounded opaque values. An explicitly public registration does not use
an unsolicited secret field. Incompatible authentication methods or callback
addresses keep the connection unavailable and produce field-level diagnostics
without printing identifiers or credentials.

The connection is ready only after authenticated MCP catalog discovery succeeds.
This verifies access, not a person's identity, and does not read task content.
Failed replacement sign-in retains the saved grant. Disconnect removes the local
grant while retaining Vellum's public registration for reconnection; users can
also revoke access in ClickUp.

The directory, tool search and tool details share one canonical plugin identity.
The complete live catalog retains provider descriptions and schemas. Schemas
load through deferred discovery, rather than entering every model prompt.
Published tools can cover tasks, Docs, comments, Chat, time tracking, workspace
hierarchy and reporting. Actual connection permissions and catalog determine
available tools; this does not promise every ClickUp REST API endpoint.

Writes use existing App Actions, exact-input/account/grant/schema-bound reviews,
MCP policy, privacy checks and audit receipts. Mutation and timer-start/stop
operations cannot use the read-only path even if incorrectly annotated. Unknown
write outcomes are never automatically replayed. No parallel specialist agent,
credential store, execution runtime or API-key route is added.

The connection panel reuses existing layout and states, with ClickUp's official
icon from `https://clickup.com/favicons/apple-touch-icon.png`. It reserves the
OAuth popup before awaiting the backend; blocked popups retain a continuation
link. Exact-origin messages and local status polling close the completed popup
and return focus to the original app. Electron must restart to load the updated
provider launch allowlist. Extra server widgets or elicitations remain subject to
host support.

ClickUp workspace permissions, plan-dependent MCP limits and provider approval
apply. Connection verification/catalog reads do not demonstrate successful
execution of every tool or every natural-language task.

Sources: [ClickUp MCP overview](https://help.clickup.com/hc/en-us/articles/33335772678423-What-is-ClickUp-MCP),
[setup instructions](https://developer.clickup.com/docs/connect-an-ai-assistant-to-clickups-mcp-server-1),
[supported tools](https://developer.clickup.com/docs/mcp-tools),
[protected resource](https://mcp.clickup.com/.well-known/oauth-protected-resource),
[authorization metadata](https://mcp.clickup.com/.well-known/oauth-authorization-server).
