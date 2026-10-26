# Notion connection

Plugins → Notion → Sign in with Notion connects to `https://mcp.notion.com/mcp`.
The official server supports dynamic public-client registration and S256 PKCE.
The scope is `default`; no token or developer app secret is pasted into Vellum.
Its fixed callback is `http://127.0.0.1:8000/api/plugins/notion/oauth/callback`.

`OfficialMcpOAuthService` shares the existing Airtable connection lifecycle and
OS credential record implementation. Provider endpoints, contracts and identity
verification stay provider-specific. Tokens live under `vellum.plugins.notion`
in the system credential store. Public app registration survives disconnection
for reconnection. Expired, cancelled or stale callbacks cannot replace a grant.
The isolated desktop OAuth child closes and restores the original app after the
flow finishes; browser popups also use status polling and exact-origin messages.

Notion identity is verified using the official `notion-get-self` MCP operation,
which returns user and workspace metadata. Tokens are never sent to Notion's
separate REST API. The complete live catalog is validated before ready status.
Provider names containing hyphens remain exact in MCP calls; model-facing names
use underscores. Published read-only annotations decide reads versus reviewed
changes; unknown annotations default to requiring review.

ToolRegistry and tool search provide deferred discovery, not a Notion specialist
or a schema dump in the initial prompt. All published tools remain discoverable;
the catalog and Notion's current permissions and plan limits are authoritative.
UI tool descriptions, original JSON schemas, real logos and official source links
use the same catalog as the agent. No unrelated Notion skills are auto-installed.

Writes use `notion.mcp.execute` and the existing PluginMcpRuntime, approvals and
App Action receipts. Exact account, workspace, grant, arguments and schema must
match the review. A queued asynchronous write is acknowledged as pending rather
than completed; use its published status tool to verify completion. Provider
errors and ambiguous network failures never become success or replayed writes.
File staging/download metadata does not automatically upload local bytes or run
downloaded skills. Those remain separate explicit operations.

Official sources:
- https://developers.notion.com/guides/mcp/get-started-with-mcp
- https://developers.notion.com/guides/mcp/mcp-supported-tools
- https://mcp.notion.com/.well-known/oauth-authorization-server
- https://mcp.notion.com/.well-known/oauth-protected-resource
