# Linear MCP connector

Vellum uses Linear's official hosted MCP server at
`https://mcp.linear.app/mcp`, matching the endpoint in Codex's Linear plugin.
One `linear` plugin owns its logo, connection settings, tools and single MCP
server. It appears under MCP servers without a second connection or skill bundle.

## Connect

Open Plugins or MCP servers > Linear > Sign in with Linear, then follow Continue
to Linear. The official MCP SDK discovers authorization metadata, registers a
public client and performs OAuth/PKCE. Each local user approves their own Linear
account/workspace. Vellum saves the verified grant in the existing OS credential
entry `vellum.plugins.linear` / `connection-v1`; it never shares a developer's key
with other users. Refresh tokens and client registration remain in that same
entry. OAuth callbacks use the local API at
`http://127.0.0.1:8000/api/plugins/linear/oauth/callback`.

OAuth is the only Linear sign-in method. The API-key form, key staging routes
and key-connect action are removed; legacy key records are not usable. Sign-in
verifies `get_user(query="me")` and `get_workspace` through the same official MCP
resource before saving the grant. MCP OAuth tokens are never sent to Linear's
GraphQL API. The callback removes the authorization code from the return URL,
shows a pending page until verification finishes, then redirects to Linear's
plugin details in Vellum. The returning view resumes flow polling and displays
the actual completed, failed or cancelled result.

Connection changes use UI-only App Actions. Failed, cancelled or expired
replacement sign-ins preserve the previous OAuth connection. Disconnect clears
local authorization and cancels pending sign-ins; revoke access separately in
Linear when needed. Per-user means separate local OS profiles/installations;
this local API is not a hosted multi-tenant authentication server.

## Tools and confirmation

Credential-free tool definitions were captured from Linear's official MCP server
on 2026-10-23: 68 tools from the verified OAuth connection, covering issues, teams, projects, comments,
labels, documents, cycles, milestones, releases, attachments, notifications and
other currently exposed operations. Paginated discovery follows all pages.

Vellum registers task tools such as `linear_list_issues`, `linear_save_issue`,
`linear_list_projects` and `linear_save_comment` with their published argument
schemas. Common issue tools (including workflow-status and label lookup) are directly
available; the rest use progressive tool search. Plugin and MCP names are not
specialist profiles: the main agent uses these tools itself, and the delegation
schema only accepts actual profile IDs from AgentCatalog.

Native calls and the existing deferred bridge use the same ToolRegistry,
permissions, provider adapter and context budget. There is no generic GraphQL
request envelope or separate recent/create issue helper. The old GraphQL compiler,
vendored API schema, agent tools, routes and operation-browser UI are removed.
Identity and workspace checks also use the official MCP tools; there is no
remaining Linear GraphQL transport.

Live discovery on tool use, Verify connection or Browse tools refreshes an
in-memory, credential-bound schema cache and invalidates the existing agent
runtime when tools change. OAuth completion also captures the live catalog. A
restart falls back to the bundled public definitions until the next refresh;
metadata-only plugin browsing never starts a remote connection. Current accounts
can expose different tools; the refreshed catalog is authoritative. The bundled
snapshot is public metadata, not workspace data or an independent tool registry.

The shared MCP runtime resolves only the requested connector and its credentials
within the registry's request-local snapshot, rather than resolving unrelated
servers on every call. This optimization applies to other MCP connectors too.

Read-only tools run through PluginMcpRuntime. Unannotated tools and writes stage
`linear.mcp.execute` through AppActionRuntime. Review binds the exact arguments,
account, workspace, credential and live tool schema. Confirmation authorizes the
existing operation-bound MCP approval, consumed once before the remote call.
Transport credentials are frozen to that connection, and writes never retry
automatically. Provider errors and unsuccessful results are not successful writes.
A pending receipt ends the model turn and is never a claim that an issue exists.

The confirmation receipt includes a typed `linear_review` preview: a plain action
heading, issue title, full description, workspace and named fields such as team,
status, labels, assignee and priority. UUID references are resolved through MCP
before review. The preview is presentation data; exact provider arguments and
credential/schema bindings remain unchanged. Creation uses a **Create issue**
button and updates use **Update issue**. Empty, cleared and unchanged descriptions
are distinguished. Model tool calls preserve description, status and label inputs.

Issue descriptions must be grounded in the request, retained conversation or
relevant project notes. Vellum does not automatically receive Codex chats or live
source changes. Its generic file tools are confined to the notes vault/browser
cache; missing project-change evidence requires a supplied change summary.
Requested completion maps to the team's actual workflow status, while labels are
resolved separately from the workspace's real labels.

Gemma's upstream renderer hides top-level parameters named `description` and
`type`. The adapter exposes portable aliases such as `body` and `field_type`,
then restores the exact official field names before transport. This does not
change the provider API or ask users to format GraphQL. The issue tool requires
an explicit body slot so descriptions cannot be silently omitted: a string sets
the description, null leaves an existing description unchanged, and an empty
string explicitly clears it (or intentionally omits it on creation). New issues
without an explicit description field fail before review rather than dropping
user-supplied context. Independent team/status/label reads can be batched when
the team name is already known.

## Scope and verification

This integration exposes the official MCP server's tools, not every field of
Linear's larger GraphQL API. Account permissions, team access, workspace roles
and plans apply. Attachment tools include the workflows the server actually
publishes; their presence does not claim a new Vellum file-picker or local binary
transfer flow. No webhook receiver or ongoing subscription is silently started.

The Linear capability contract is v2. Guarded endpoints are status,
`/mcp/tools`, `/mcp/read` and OAuth status. Start/cancel,
connection lifecycle and workspace writes use App Actions. Provider redirects
use a separate loopback/state-validated callback. Tokens, callback codes, PKCE
verifiers and raw provider errors never enter public results.

See [verification](verification/linear-mcp-2026-10-23.md) for executed checks and
remaining attended sign-in/provider-write boundaries.
