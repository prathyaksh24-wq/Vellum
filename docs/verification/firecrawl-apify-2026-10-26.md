# Firecrawl and Apify verification — 2026-10-26

The user completed both browser consent flows and reported returning to Vellum.
The API independently reported both connections ready with `auth_type=oauth`.

Observed on the running development checkout:

| Provider | Published tools | Read-only | Reviewed operations |
| --- | ---: | ---: | ---: |
| Firecrawl | 30 | 20 | 10 |
| Apify | 28 | 17 | 11 |

- Existing configured credentials were first verified through typed App Actions.
  Their optional connection method remained separate from default OAuth.
- Both official authorization servers accepted public-client registration and
  returned the expected authorization URLs with S256 PKCE and provider scopes.
- Both prepared discovery flows could be cancelled without replacing the saved
  credentials. The user subsequently completed new OAuth flows in Vellum.
- Firecrawl verified team access through its read-only credit-usage MCP operation.
  It does not provide a user profile; the UI and contract preserve that distinction.
- Apify verified the authorizing account through its user-metadata endpoint.
- Both full selected catalogs were validated and exposed through deferred search.
  Firecrawl monitor tools and Apify Actor/dataset/schedule tools were found.
- `/api/plugins` contained one entry for each provider.
- A fresh Python process loaded both saved OAuth authorizations and reported
  ready status with the same tool counts.
- Backend health, both connection components and both bundled official logo
  URLs returned HTTP 200. Existing credentials never appeared in tool output.
- Python/JSX source syntax was parsed. Reviewed Action Parity mappings were
  recorded. The scoped mechanical UI detector returned no findings.

No local tests or builds ran, following the user's instruction. Unrun regression
sources cover OAuth without operator keys, optional credential adoption, failed
replacement preservation, disconnect behavior, forced Actor/browser reviews,
exact-input/grant bindings, deferred schemas, pending runs, endpoint pinning and
the retired unreviewed Actor path. Legacy unit fixtures were scoped explicitly
to unmanaged configurations.

No scrape, crawl, remote browser interaction, Actor run, schedule or other
provider write was executed. Provider metadata and successful OAuth do not prove
every operation or natural-language task. Real refresh-token expiry and native
Electron popup behavior were not attended verified. Desktop host changes require
an Electron restart. No Git publication was performed for this task.
