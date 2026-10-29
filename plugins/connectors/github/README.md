# GitHub

One Vellum GitHub connection authorizes both transport paths. Compatible operations
use the bounded GitHub CLI adapter; unsupported operations and safe failures use
GitHub's official hosted MCP server. A timeout or uncertain write never triggers
automatic replay. Read/write permissions, OAuth scopes, organization policies and
the server's available toolsets still apply.

Sign in from Plugins → GitHub. Vellum reuses its configured
`VELLUM_ACCOUNT_GITHUB_CLIENT_ID` and `VELLUM_ACCOUNT_GITHUB_CLIENT_SECRET` and the
registered `http://127.0.0.1:8000/api/accounts/callback/github` callback, with a
separate PKCE/state-bound plugin flow. This does not switch the active Vellum
identity or modify the global `gh` account. Authorization is stored in the OS
credential store under `vellum.plugins.github`, never written to `.env` or returned
to the frontend. Disconnect removes this connector's local authorization. Revoke
the application in GitHub's account settings to withdraw the provider grant.

The callback verifies the account and official MCP catalog before marking the
connection ready. A popup reports completion to its exact opener origin, closes
and focuses the original app; polling also closes the retained popup handle if
cross-origin navigation has severed its opener. The popup never redirects to the
full Vellum app. Non-popup flows return to the GitHub detail page. Declined, expired,
cancelled, replayed or stale callbacks cannot replace the saved connection.

Desktop sign-in opens only the local backend's validated OAuth launch route in a
dedicated child of the existing workspace. That child has no preload/native bridge,
Node access or device permissions. Completion closes it and focuses its original
owner. Navigation into the workspace is intercepted, so the full app cannot load
inside the authentication window.

The agent discovers `github_mcp_catalog`, `github_mcp_describe`,
`github_mcp_read` and `github_mcp_execute` through the existing tool-search owner.
Catalog search returns small pages of summaries; describe returns one schema.
The complete catalog is cached by the connection revision in the backend, rather
than injected into every model prompt. It refreshes on reconnect, explicit Verify
or Browse tools, or the first operation after backend restart.

Writes pass through `github.mcp.execute` and the existing App Action confirmation
and receipt system. Reviews bind the account, connection revision, exact arguments
and schema. The connection revision is a random, opaque generation changed on
every sign-in; token values are not review fields. Provider approval is consumed
for both CLI and MCP execution. Labels, descriptions and other published fields
are preserved; inputs the CLI cannot represent exactly remain on MCP.

The legacy server-configured GitHub transport used by coding integrations remains
separate; public conversational GitHub tools use this connector's grant and review
path. Existing `GITHUB_PAT` values are not silently adopted as a plugin sign-in.

Sources: [official GitHub MCP server](https://github.com/github/github-mcp-server),
[remote server](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md),
[GitHub CLI](https://cli.github.com/manual/gh_api).
