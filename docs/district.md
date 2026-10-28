# District official MCP connector

Vellum connects to `https://mcp-server.district.in/mcp`. District's official
ChatGPT listing names restaurants, movies, theatres, showtimes, events, venues
and artist discovery. Booking/payment availability must come from the actual
connection's published catalog; marketing descriptions do not establish tools.

## Local connection

Open Plugins → District → Sign in with District. Its own browser page handles
account verification; do not enter OTPs or tokens in Vellum chat. Vellum registers
its own client named Vellum with callback
`http://localhost:8000/api/plugins/district/oauth/callback`, S256 PKCE and one-use
state. Browser popup completion focuses the original app; Electron needs a full
restart to load the updated OAuth launch allowlist.

Public authorization metadata advertises /authorize, /token and /register,
code/refresh grants and S256. It does not advertise scopes or a protected-resource
identifier. The protected-resource path returned 404. This connector omits
unadvertised scope/resource indicators and pins all requests to District's own
endpoints. Its callback policy is not inferred from Zomato's. Only a successful
OAuth exchange and authenticated catalog verification establish readiness.
A rejected callback is surfaced; no other client's redirect or credentials are
substituted. No production app, hosted relay or access request is created here.

District currently returns client_secret_post app authentication, even when a public client was requested. Vellum retains the issued client secret in its OS credential record and uses it only for token exchange/refresh. It is never returned to the browser or chat. A bounded one-time replacement recovers the initial shape-only registration whose secret was not retained. Later sign-ins reuse the complete registration.

Tokens and registration live in the existing OS credential store. Optional
expiry/refresh metadata is validated without inventing a lifetime. Refresh
responses without rotation retain the saved refresh token. Failed replacement
sign-in preserves the existing grant. Disconnect removes local authorization
and rotates its revision while retaining the registration.

## Tools and changes

PluginRegistry, ToolRegistry, PluginMcpRuntime and App Actions retain ownership.
The complete published catalog preserves original descriptions/schemas. Tool
search defers schemas until needed; no specialist agent is added. The detail,
tool list and review use the official purple app icon from District's ChatGPT listing.

The verified catalog exposes 15 tools: 14 discovery/detail reads and one table
reservation creation operation. District currently omits read-only hints, so the
14 reviewed read operations have an exact provider-specific classification;
unknown tools keep the provider/default classification. Named mutations remain reviewed even if incorrectly
annotated as reads. Changes bind exact inputs, account, grant and schema to the
canonical approval and audit receipt. Order/booking/payment results remain pending
unless a recognized confirmed state and order/booking ID establish completion.
Unknown writes are never replayed automatically. No customer-data read, booking
or payment is part of connection verification. Provider widgets are not embedded
by this change; matching interactive cards needs separate MCP UI host support.

Sources: [official listing](https://chatgpt.com/plugins/plugin_asdk_app_699d871f7dfc819192b74090657868fb),
[authorization metadata](https://mcp-server.district.in/.well-known/oauth-authorization-server),
[provider consent](https://mcp-server.district.in/consent).
