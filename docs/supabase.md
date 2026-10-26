# Supabase platform connector

Vellum connects to Supabase's official hosted MCP server using per-user OAuth
and the existing local credential store, ToolRegistry, PluginMcpRuntime and App
Action reviews. It does not reuse the Supabase project URL or publishable key
that may back Vellum's own account sign-in.

The fixed server URL selects all documented feature groups:

```text
https://mcp.supabase.com/mcp?features=docs,account,database,debugging,development,functions,branching,storage
```

The protected resource is exactly `https://mcp.supabase.com/mcp`. Supabase's
metadata advertises authorization at `https://api.supabase.com/v1/oauth/authorize`,
token exchange at `/v1/oauth/token` and client registration at
`/platform/oauth/apps/register` on that same host. Unlike the earlier public-client
connectors, its advertised token methods are `client_secret_basic` and
`client_secret_post`. The registered client secret is stored only in the bounded
OS credential record and is used only for the fixed token endpoint. It never
enters the browser authorization URL, public status, App Action arguments or
receipts. Other connectors retain their existing public-client authentication.

Callback: `http://127.0.0.1:8000/api/plugins/supabase/oauth/callback`.

## Connection and tools

Open Plugins → Supabase → Sign in with Supabase. Registration creates a local
Vellum client identity at Supabase; it does not itself grant account access.
The user selects the intended Supabase organization and approves scopes in the
provider's browser flow. Catalog discovery must succeed before Vellum reports
the connection ready. Failed or cancelled replacements retain an older saved
grant. Disconnect removes the user grant while retaining client registration
for reconnection.

The complete published tool catalog loads on demand. It includes the enabled
Database, Debugging, Development, Edge Functions, Account, Docs, Branching and
Storage groups as allowed by the granted account permissions and plan. Storage
is explicitly enabled because Supabase disables it by default. No placeholder
tools or fixed tool-count promises are used.

SQL execution, migrations and cost authorization always use the reviewed change
path, even if a provider version annotates one as read-only. Other tool annotations
and exact schemas are preserved. Results are untrusted provider evidence and
retain the shared redaction and result budget. The connection check does not
read project records or invent a verified person's name or email.

Supabase can require additional form or URL elicitations for destructive SQL,
paid resource creation or secret entry. Vellum does not set `skip_elicitations`
or automatically approve those prompts. The current shared MCP transport does
not provide an attended provider-elicitation UI, so operations requiring such a
prompt can remain unavailable even after account connection. This is separate
from Vellum's own exact-input confirmation, and must not be reported as success.
Exposing a tool does not prove every operation or plan-specific feature works.

Sources: [official MCP documentation](https://supabase.com/docs/guides/ai-tools/mcp),
[protected-resource metadata](https://mcp.supabase.com/.well-known/oauth-protected-resource/mcp),
[OAuth metadata](https://api.supabase.com/.well-known/oauth-authorization-server).
