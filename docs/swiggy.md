# Local Swiggy Food and Instamart

Vellum connects Food at `https://mcp.swiggy.com/food` and Instamart at
`https://mcp.swiggy.com/im`. The `/instamart` path is not the documented endpoint;
a 401 from it only establishes authentication middleware, not route existence.
Dineout and Scenes are outside this integration's selected scope.

## Local sign-in

Open Plugins → Swiggy, select Food and/or Instamart, then Sign in with Swiggy.
The proposed local callback is now implemented at
`http://localhost:8000/api/plugins/swiggy/oauth/callback`.
Swiggy handles phone/OTP entry in its own consent UI. Vellum never collects OTPs.
The public desktop client identifies itself as Vellum, uses DCR, S256 PKCE and
JSON token exchange/refresh with the current advertised resource
`https://mcp.swiggy.com`. Rotating tokens persist in the existing OS credential
store, never `.env`, manifests, chat or logs. The guarded callback uses exact
state, one-use code handling, a nonce CSP and exact-origin completion messaging.
The OAuth child closes after catalog verification and focuses the original app.
Electron needs a full restart for its added provider launch allowlist.

Swiggy's current developer form explicitly says localhost is supported; its
production URL field should not contain localhost. Production review, agreements,
public callback hosting and rollout are separate work. Local registration and
OAuth must be verified before claiming they work; metadata discovery alone does
not establish acceptance. Failed replacement sign-in preserves the prior grant.
Disconnect removes local authorization while retaining the public registration
and selection; it does not call Swiggy's session-wide logout endpoint.

## Services and tools

One OAuth/keyring owner stores the grant and selected services. A typed UI-only
App Action changes selection, rotates the authorization revision, cancels stale
flows and invalidates tool discovery/reviews. Turning a service off is enforced
at the MCP runtime, not just hidden in the panel. Both services may be switched
off without destroying the grant. Enabling a service with a saved grant verifies
its catalog before saving the selection. There is no second preference store.

PluginRegistry, ToolRegistry, PluginMcpRuntime and App Actions retain ownership.
Food and Instamart are distinct manifest connectors pinned to their exact URLs.
Agent catalog names include `food__` or `instamart__`; the runtime routes to that
connector and restores the original tool name only at the transport boundary.
All published schemas and descriptions are preserved. Discovery loads compact
summaries and one requested schema rather than every schema in the initial
prompt. There is no dedicated Swiggy agent. Real Food/Instamart logos come from
Swiggy's own Builders Club brand assets.

## Changes and checkout

Cart/address edits, checkout and unknown mutations require exact-input,
account/grant/schema-bound review and canonical MCP approval/audit. Order
preparation reads the current service-specific cart and requires a selected
address, payment choice, priced nonempty items and a matching Instamart delivery
address. Its cart snapshot is bound to the confirmation and rechecked before
checkout. Changes require another review. Provider prices can still change
between the final read and submission because no provider atomic price-lock
precondition was established. No purchase has been verified here.

A returned order/payment result is pending unless it includes a recognized
confirmed state and order ID. Multi-store/ambiguous results require separate
status checks. Unknown writes are never automatically replayed. Payment and
checkout runtime behavior, live field shapes and exact amount units must be
verified in the approved development environment before real-money use.

Provider UI resources/widgets are not embedded by this change. The current
host uses the normal data/text path; matching ChatGPT's interactive checkout
cards requires separate sandboxed MCP resource/bridge support.

Sources: [authentication](https://mcp.swiggy.com/builders/docs/start/authenticate/),
[Food](https://mcp.swiggy.com/builders/docs/reference/food/),
[Instamart](https://mcp.swiggy.com/builders/docs/reference/instamart/),
[developer application](https://docs.google.com/forms/d/e/1FAIpQLSfUhtaGOQjnxS0o8uHFZwZGNxJhJzyYhxiYVotlqdBCpizpUw/viewform),
[widgets](https://mcp.swiggy.com/builders/docs/build/widgets/).
