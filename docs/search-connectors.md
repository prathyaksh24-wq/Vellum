# SerpAPI, Exa and Tavily

Vellum uses the official hosted MCP servers through its existing
`PluginMcpRuntime`, tool registry, privacy checks and App Action receipts.
No additional specialist agents or per-request npm processes are introduced.

| Provider | Connection | Published tool catalog observed on 2026-10-26 |
| --- | --- | --- |
| SerpAPI | Local UI key form, or explicit adoption of the existing configured key | `search`, `search_table`, `search_dashboard` |
| Exa | Per-user OAuth with PKCE and public-client registration | `web_search_exa`, `web_search_advanced_exa`, `web_fetch_exa`, `agent_run` |
| Tavily | Per-user OAuth with PKCE; optional configured-key adoption | `tavily_search`, `tavily_extract`, `tavily_map`, `tavily_crawl`, `tavily_research` |

Sources: [SerpAPI's official server](https://github.com/serpapi/serpapi-mcp),
[Exa's official server](https://github.com/exa-labs/exa-mcp-server),
[Tavily's MCP documentation](https://docs.tavily.com/documentation/mcp).
These are the published MCP tools, not a claim to expose every REST endpoint.
SerpAPI's generic search retains its provider engine parameters. Its optional
table/dashboard MCP App interfaces are not rendered by Vellum's current host;
tool results remain available.

## Choosing web search

The Web search control on each of these plugin pages uses Vellum's shared
dark `VSelect` with keyboard navigation, selection state and availability labels.
It dispatches `settings.web_search.set` through the existing settings runtime.
The canonical config writer persists `WEB_SEARCH_BACKEND` and clears the settings
cache, so the next search uses the saved choice without a restart.

Users can also edit the repository's `.env` or provide the environment setting:

```dotenv
WEB_SEARCH_BACKEND=exa
```

Supported choices are `serpapi`, `exa`, `tavily`, `brave`, `ddgs`, and `auto`.
With no explicit search preference, the existing `WEB_BACKEND` shared preference
still applies. `WEB_SEARCH_BACKEND=auto` explicitly overrides it. Automatic
selection prefers SerpAPI, then Exa, Brave, Tavily and DuckDuckGo according to
availability, retaining per-call fallback. Explicit search selection is exclusive:
an unavailable or failing Exa does not silently send the query to SerpAPI.
Results identify the provider used. Extraction retains its existing separate
`WEB_EXTRACT_BACKEND` selection behavior.

General and sports web searches respect this registry. YouTube's dedicated
SerpAPI engine/transcript features remain provider-specific; their saved key and
enablement come from the same SerpAPI connection, with the existing generic
web-search fallback where applicable.

## Authorization and tool disclosure

- SerpAPI keys enter only the guarded local staging route. The connection action
  receives an expiring, one-use opaque reference. Account API verification precedes
  MCP catalog discovery and replacement of the old key. Catalog listing alone
  is insufficient because SerpAPI exposes discovery without authentication.
- Exa OAuth requests `mcp:tools`, using `https://mcp.exa.ai/mcp` as its protected
  resource. Its official server verifies the OAuth JWT. The authenticated URL
  selects all four currently documented tools, including advanced search.
  A plain API key cannot masquerade as a verified OAuth connection. Existing
  unmanaged REST configurations continue working until migrated.
- Tavily requests `openid offline_access`. Its advertised protected resource is
  exactly `https://mcp.tavily.com/mcp`, even when the HTTP transport uses a trailing
  slash. Using the root origin caused `invalid_target` before consent; this is
  corrected. Known OAuth request errors no longer say the user declined access.
- Grants, refresh tokens and adopted keys stay in the existing bounded OS keyring
  record format. New secrets are not written to `.env`. Failed replacements keep
  the previous saved connection. Disconnect leaves a revisioned managed tombstone
  and never silently revives an older configured key.
- Status, prompt setup and tool-registry construction do not fetch every provider's
  schemas. Generic catalog/describe tools and cached native operations participate
  in the existing deferred tool search; a selected provider loads only its needed
  schema. Transport and credentials are pinned to the official endpoint.
- Exa's `agent_run` starts billable research through an exact-input App Action
  review. A call containing only a nonempty `runId` is a read of an existing run,
  and requires no new-start confirmation. An accepted run without confirmed
  completion remains pending; Vellum must retrieve its result, not restart it.
- Exa and Tavily's MCP surfaces here do not provide a verified user profile.
  Reviews bind to the authorized grant rather than inventing a person or email.

The logo assets are downloaded from each provider's official site and stored
locally as `serpapi.png`, `exa.png`, and `tavily.png`. Tool lists, plugin details
and applicable change reviews reuse those assets.

See [verification](verification/search-connectors-2026-10-26.md) for evidence and
remaining validation limits.
