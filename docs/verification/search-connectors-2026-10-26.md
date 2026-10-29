# Search connector verification — 2026-10-26

## Observed live

- SerpAPI's existing configured key passed the official account API check and
  complete MCP catalog discovery. Connection action returned `applied`; status
  is `ready`, `connected: true`, `auth_type: configured_api_key`, with three tools.
- Exa public-client registration and OAuth flow succeeded. The user approved
  consent and reported returning to Vellum. Backend status independently showed
  `ready`, `connected: true`, `auth_type: oauth`, with four published tools.
- Tavily initially returned `invalid_target` before displaying consent. A
  credential-free HTTP challenge identified its exact protected-resource metadata
  at `/.well-known/oauth-protected-resource/mcp`. The corrected resource is
  `https://mcp.tavily.com/mcp`. An authorization-entry request then returned HTTP
  302 to `auth.tavily.com/authorize`, without an OAuth error. After the reload,
  the user completed consent and reported returning to Vellum. Backend status
  independently showed `ready`, `connected: true`, `auth_type: oauth`, five tools.
- Guarded catalog endpoints returned HTTP 200 for all three. Exa's `agent_run`
  is presented as review-required; its other three tools are reads.
- SerpAPI and Exa grants remained ready after the backend restart and loaded in
  a separate Python process. Tavily was connected after that restart; its OAuth grant also loaded ready in a separate Python process.
- The frontend on port 5173 serves the updated Web search component referencing
  the shared styled `VSelect`. Official PNG assets have valid PNG headers.
- The live App Action catalog exposes the connection lifecycle, provider operations
  and `settings.web_search.set`. No SerpAPI OAuth action is advertised.

## Source checks and authored regressions

Python AST parsing covered 38 source/regression files. Babel/JSX parsing covers the changed source and authored regression
files. Reviewed handler fingerprints are updated only for the changed production
entry and connection components. The static Impeccable detector returned `[]` for
the new connection/settings components before the native selector was replaced;
the replacement reuses the existing shared selector.

Authored regression coverage addresses key verification/redaction, one-use staging,
failed replacement preservation, managed disconnect persistence, exact OAuth
resources, error categorization, deferred schemas, Exa research polling versus
new-run reviews, OAuth popup ownership, exclusive provider selection and the styled
selector's actual App Action dispatch. Existing registry assertions are updated
for the intentional exclusive-search behavior. The legacy Tavily MCP assertion
now expects a bearer header instead of a credential-bearing URL.

## Limits

No test suites or builds were run, per the user's instruction. No web searches,
page crawls or paid research runs were issued for these checks. The full chat-to-
provider response path, UI appearance at physical window sizes and Electron child
window behavior were not exercised. The browser sign-in completion is user-reported
and independently corroborated by local connection status/catalog metadata.
The desktop host's new Exa/Tavily OAuth allowlist takes effect after a full Electron
restart. Task-scoped `git diff --check` is clean. No branch, commit, push or PR was created for this task.
