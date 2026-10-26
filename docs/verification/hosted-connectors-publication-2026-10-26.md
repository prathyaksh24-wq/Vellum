# Hosted connector publication — 2026-10-26

The publication branch is `codex/hosted-mcp-connectors`, based on main at
`3b8c298` after the merged Slack PR #230. It includes Airtable, Notion, Firecrawl,
Apify, SerpAPI, Exa and Tavily, their shared connection owners, deferred tools,
review controls and web-search selection. Existing main's Linear credential
fingerprinting, clock/confirmation fixes and unrelated voice/browser/response
behavior are retained.

The running development checkout has unrelated dirty work. New provider files
were selected explicitly; large shared files received only connector and search
preference changes. No `.env`, saved grants, databases, runtime logs, cached
catalog responses, model files or private screenshots are included. Slack's
bounded credential implementation is extracted into a shared owner while keeping
its storage format and service names compatible.

## Verification performed during publication

- Python AST parsing of 79 changed/new Python files.
- Babel/JSX parsing of the changed served React entry, nine shared/connection
  components, the API adapter, seven authored UI regression files and two desktop
  JavaScript files.
- Reviewed Action Parity source registration and control mappings, then computed
  fingerprints against the actual isolated-branch source. The production entry
  has 961 handlers; fingerprints from the broader development UI are not copied.
- Task-scoped source inspection for common credential patterns found no matches.
- Git whitespace checks passed. Provider JSON/YAML manifests are declarative;
  no new package dependencies or workflow changes are introduced.

No local tests or builds ran, as requested. Regression sources are included but
are not claimed passing. No CI workflow was manually dispatched or rerun.

## Earlier live development evidence

The user completed the six OAuth flows and returned to Vellum. SerpAPI's existing
key was adopted after account verification. The local backend confirmed saved
connections and published MCP catalogs: Airtable 54, Notion 65, Firecrawl 30,
Apify 28, SerpAPI 3, Exa 4 and Tavily 5 tools. These counts describe the catalogs
observed during development, not permanent provider API coverage guarantees.

These checks do not establish that every operation or full chat-to-provider task
succeeds. No provider writes, paid searches/research runs, physical UI inspection,
or native Electron OAuth window verification was performed for this publication.
Each user must authorize their own accounts; provider permissions, plan limits
and API availability continue to apply. Electron needs a restart for its expanded
OAuth child-window allowlist.

Earlier implementation notes remain historical evidence:
[Airtable](airtable-2026-10-26.md), [Notion](notion-2026-10-26.md),
[Firecrawl/Apify](firecrawl-apify-2026-10-26.md),
[search providers](search-connectors-2026-10-26.md).

## PR #231 hosted CI correction

Inspected CI run 40285438754 at head f550dbc. Three of six jobs failed:
backend tests (4 failed, 3621 passed, 28 skipped), frontend Vitest (2 failed,
571 passed), and the Python audit's exception-expiry guard. Production build,
secret scanning, npm audit and dependency review passed. No manual CI rerun
was dispatched.

The three Notion review tests used a synthetic parent ID with ten consecutive
digits that the privacy boundary scrubbed. Use realistic UUID fixtures instead;
privacy classification and exact-operation checks are unchanged. The sports
fixture now explicitly selects SerpAPI and matches its credential-owning client's
keyword-only construction. Registry-selection behavior retains separate tests.
The Apify and Firecrawl copy assertions match "official hosted MCP server".

Rechecked PyPI ChromaDB release metadata and all four listed GitHub advisories
on 2026-10-26. Latest is still 1.5.9 and first_patched_version remains null for
all four. Source still constructs only embedded PersistentClient/EphemeralClient
instances; no Chroma HTTP client, server or trust_remote_code use was found.
Renewed the same exceptions through 2026-11-09 without adding exemptions or
weakening the expiry/audit gates. This is not a claim of a fresh full audit.

Python/JavaScript syntax and scoped whitespace checks cover the corrections.
No local test suites or builds were run. The next push starts normal hosted CI;
its result is separate from these source checks.
