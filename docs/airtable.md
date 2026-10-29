# Airtable connection

Vellum uses Airtable’s official hosted MCP server at `https://mcp.airtable.com/mcp`.
Open Plugins → Airtable → Sign in with Airtable. Automatic public-client registration
starts OAuth with S256 PKCE; no personal access token or developer client secret is needed.
Select the bases, apps and workspaces on Airtable’s consent screen. The fixed callback is
`http://127.0.0.1:8000/api/plugins/airtable/oauth/callback`.

Authorization stays in the OS credential store under `vellum.plugins.airtable`,
using bounded atomic records shared with the Slack connector. The format can read
existing Slack records; it does not migrate or replace their credentials.
Refresh tokens rotate under the connection lock with no automatic refresh retry.
One-use state, expired/cancelled flow checks and connection revisions prevent an
old callback from replacing a newer authorization. The original app polls its flow;
an isolated desktop OAuth child closes after verification and restores the app.

The connection becomes ready only after `meta/whoami` and live MCP catalog validation.
Verification reads identity and tool metadata, not base records. Account display falls
back to Airtable’s verified user ID because the documented MCP scopes do not request email.

All tools published by the connected server retain their exact descriptions and JSON
schemas. Catalog summaries and individual schemas load on demand through ToolRegistry
and tool search. There is no Airtable specialist and no initial prompt schema flood.
After a backend restart, `airtable_mcp_catalog` warms the native-tool cache when needed.
The shared PluginMcpRuntime pins credentials to the official endpoint and retains its
privacy checks, audit log and approval store. Writes require a readable App Action review
bound to account, grant revision, published schema and exact arguments. Ambiguous failures
are reported without replaying the write or claiming success.

Coverage includes bases, tables, fields, records, comments, forms, interfaces and
automations when published by Airtable. The live catalog is authoritative; this is
not a promise that every REST API endpoint or UI feature is available through MCP.
Workspace roles, granted resources, organization approval, rate and plan limits apply.
Airtable automation drafts require activation in Airtable, and Script actions have
provider limitations. The installation’s public client registration is reused across reconnects.
Disconnect removes local authorization and retains that public identifier; revoke the grant under
Airtable → Integrations → Third-party integrations to withdraw provider access.

Official sources:
- https://airtable.com/developers/agents/mcp/getting-started
- https://airtable.com/developers/agents/mcp/tools
- https://airtable.com/developers/web/api/get-user-id-scopes
- https://mcp.airtable.com/.well-known/oauth-authorization-server
- https://mcp.airtable.com/.well-known/oauth-protected-resource
