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
