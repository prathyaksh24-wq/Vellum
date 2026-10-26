# Vercel MCP connector

Vellum connects to the official `https://mcp.vercel.com` server using its own
OAuth public-client registration, PKCE, and the existing OS credential store.
The protected resource is exactly `https://mcp.vercel.com/`, including its trailing
slash. Authorization, registration and token endpoints are pinned to the ones
advertised by Vercel's MCP authorization metadata.

The client registers as **Vellum**, application type `native`, with callback
`http://127.0.0.1:8000/api/plugins/vercel/oauth/callback`. It never impersonates
another approved client, reuses another product's client ID, or treats an
unrelated CLI login as proof that Vellum's MCP authorization works.

## Provider approval and connection

Vercel documents a reviewed-client requirement for its MCP server. An advertised
registration endpoint does not guarantee Vellum is accepted. The connection
remains unavailable if registration, user consent, token exchange or catalog
verification fails. No placeholder ready state is used. Failed replacements
retain any previous saved grant. Once connected, each user chooses the account
and grants access to the teams they intend to use.

The connection check discovers the live catalog without reading project content
or inventing a verified person identity. The model finds operations through the
existing deferred tool search and loads exact schemas on demand. Vercel's full
documentation catalog can be larger than the catalog returned to this client;
client approval, team grants, project scope and server configuration determine
actual tools. No fixed tool-count or full-REST-API claim is made.

Writes retain App Action reviews bound to the saved account/grant, exact inputs,
schema and credential revision. The existing MCP policy, privacy and audit owners
mediate execution. Published deployment-start and CLI-execution tools always take
the reviewed path, even if a provider version labels one read-only. Deployment
creation remains pending while Vercel reports
queued/building state; a failed or cancelled deployment is not reported complete.
Do not replay an uncertain deployment creation automatically.

The plugin and tool lists reuse Vellum's real Vercel logo asset. OAuth completes
in the original app window after the popup closes. Desktop host changes require
a full Electron restart. Interactive provider widgets and any extra server
elicitations depend on host support; exposing a tool does not establish those
flows or every plan-specific capability.

Sources: [Vercel MCP setup and reviewed clients](https://vercel.com/docs/agent-resources/vercel-mcp),
[published tool reference and access limits](https://vercel.com/docs/agent-resources/vercel-mcp/tools),
[protected-resource metadata](https://mcp.vercel.com/.well-known/oauth-protected-resource),
[authorization metadata](https://mcp.vercel.com/.well-known/oauth-authorization-server).
