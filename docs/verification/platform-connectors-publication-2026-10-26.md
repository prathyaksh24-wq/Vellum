# Four platform MCP connectors — publication evidence, 2026-10-26

The branch builds on the shared infrastructure from merged PR #231 at
`06e38f9`. CI run 40337632814 passed all six jobs for that parent commit. The
new draft targets main after that merge, so its diff includes only Supabase,
Vercel, ClickUp and HubSpot plus their shared integration changes.

## Scope

Copied only the four providers' contracts, connection services, routes, App
Action controls, adapters, manifests, views, regression sources and documentation
from the running development checkout. Large shared files received only their
provider registration, discovery, preview and OAuth-window changes. Unrelated
voice, browser, automation, chat layout and other dirty work is excluded.

The shared OAuth lifecycle adds narrow app-registration/token-authentication hooks
while preserving public-client behavior for the previous providers. Confidential
credentials remain in the OS credential store. Provisioning/deployment results
stay pending until the provider reports completion; uncertain writes are not
replayed. HubSpot's app secret crosses only the guarded staging endpoint; an
opaque expiring reference crosses its UI-only confirmed setup action.

The existing CI workflow is unchanged. The draft targets main and receives its
normal test, build, audit and secret-scanning jobs.

## Verification

Python AST and Babel/JSX parsing cover changed and new sources, including authored
regressions. JSON/YAML parse, scope review, credential-pattern inspection and Git
whitespace checks cover the publication. App Action mappings and served-source
registration were reviewed before computing fingerprints against this isolated
branch: 965 production-page handlers, nine shared review handlers, and provider
panels with eight each except HubSpot's eleven. Broader development-page
fingerprints were not copied. New UI tests check official source links instead
of a brittle contiguous marketing phrase.

No local tests or builds were run. Normal hosted CI after publication is separate
evidence; no workflow was manually dispatched or rerun.

Earlier live development checks, corroborating user-completed consent:

| Provider | Connection | Observed tools | Read / reviewed |
| --- | --- | ---: | ---: |
| Supabase | Registered confidential client + OAuth | 32 | 19 / 13 |
| Vercel | Registered public client + OAuth | 238 | 144 / 94 |
| ClickUp | Registered public client + OAuth | 66 | 29 / 37 |
| HubSpot | Manually created MCP connector + OAuth | 30 | 19 / 11 |

Fresh processes loaded the saved grants from OS credentials. ClickUp's observed
ten-year token lifetime is supported without requiring a nonexistent refresh
token. HubSpot's HTTP callback uses literal localhost as its documented exception.
No account records were read or modified to verify these catalogs, and no
deployments, SQL, paid provisioning or provider writes were performed.

Catalog coverage is for the selected account/grant, not every provider REST API
or proof that every natural-language task works. Supabase elicitations, Vercel
widgets, native Electron OAuth windows and provider-specific confirmations remain
subject to host support and unperformed acceptance checks. Restart Electron for
its new launch allowlist. HubSpot public onboarding additionally needs hosted
confidential-client authorization and provider distribution approval; shared app
secrets must not ship in the desktop app. No credentials, .env files, databases,
logs, machine state, model files or private screenshots are included.
