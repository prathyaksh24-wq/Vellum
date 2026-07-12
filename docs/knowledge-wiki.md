# Vellum Knowledge Wiki

The Knowledge Wiki is Vellum's private, maintained Obsidian knowledge layer. It complements the Memory Orchestrator; it does not replace it.

## Trust boundary

`Knowledge/` is the maintained wiki and the only directory the wiki service writes. Existing Knowledge pages are the canonical working set.

`Library/` contains raw material whose current accuracy is not assumed. The wiki never reads Library files automatically. Ingestion must be explicitly requested in one of two ways:

- supply the complete content/synthesis in the request, without `source_path`; or
- provide a specific vault-relative `source_path` and set `approved_source: true` (aliases `approved_path`, `approve_source`, and `approved` are accepted).

An unapproved path is rejected even when content is also supplied. An approved path is read only for that explicit ingestion call, and raw Library files are never modified. Normal status, query, read, index rebuild, overview, and lint operations read only `Knowledge/`.

Every content page has explicit `source_trust` and structured `provenance` frontmatter. The normal values are `maintained`, `user_supplied`, `approved_path`, `trusted`, `untrusted`, `unknown`, and `mixed`. A content-only ingest is recorded as `user_supplied`; an approved path is recorded as `approved_path`.

## Layout

```text
Vault/
|-- Library/                 Raw sources; never automatically ingested
|-- Knowledge/               Vellum-maintained linked synthesis
|   |-- index.md             Content map; always consulted first
|   |-- overview.md          High-level synthesis
|   |-- schema.md            Schema and trust contract
|   |-- log.md               Append-only operation history
|   |-- entities/
|   |-- concepts/
|   |-- topics/
|   |-- projects/
|   |-- analyses/
|   |-- sources/
|   |-- inbox/
|   |-- lint/
|   `-- .history/            Prior page versions
|-- Meta/                    User profile, goals, principles
|-- Projects/                Active project working state
`-- Agent/                   Conversations and personal memory artifacts
```

## Page contract

Content pages have `id`, `type`, `title`, `description`, `sensitivity`, `status`, `created`, `updated`, `version`, `sources`, `source_count`, `source_trust`, `provenance`, and `tags`.

Page types are `source`, `entity`, `concept`, `topic`, `project`, and `analysis`. Sensitivity is explicitly `public` or `private`; private page reads and query maps use the local privacy scrubber before returning content to a model-facing caller.

`id` is the stable page identity. Pass it as `page_id`, `identity`, `stable_id`, or `id` when revising a page whose title may change. The opaque `kw-...` reference returned by query is derived from that identity, so it remains stable across revisions and deliberate renames. A same-type stable identity updates the existing page instead of creating a near-duplicate; a type conflict is an error.

Updates are idempotent. An identical upsert does not increment the version or create history. A real revision saves the previous document under `Knowledge/.history/`, increments `version`, rebuilds `index.md`, and appends to `log.md`. History is available through the API and tool without exposing raw historical text by default.

## Workflow

1. Call `status` to ensure the wiki structure exists and inspect the trust policy.
2. Call `query` to consult `Knowledge/index.md` and receive a small set of opaque page refs.
3. Call `read_page` only for selected refs.
4. Use `upsert_page` for a complete maintained page. Supply a stable identity when updating an existing entity/concept/topic/etc.
5. Use `ingest_source` only with supplied content, or with an explicitly approved source path. Include complete source synthesis and complete revised related pages, plus their source trust/provenance.
6. Call `update_overview` when the high-level map changes.
7. Call `version_history`/`history` to inspect revisions, `read_version` for one prior version, `rebuild_index` after manual Knowledge edits, and `lint` to check health.

Lint reports missing schema fields, source references, provenance, invalid trust values, broken links, duplicate titles/identities, orphan pages, stale pages, and overview drift. It never deletes or rewrites content pages; its report and log entry are written under `Knowledge/`.

## API

The stable API lives under `/api/knowledge`:

- `GET /status`
- `GET /query?q=...&limit=8`
- `GET /pages/{page_ref}`
- `GET /pages/{page_ref}/history`
- `GET /pages/{page_ref}/history/{version}`
- `POST /pages`
- `POST /ingest`
- `POST /overview`
- `POST /lint`
- `POST /rebuild-index` (also `/index/rebuild`)

API validation and wiki contract violations return a 4xx response with a useful `detail`. Unknown page refs and unavailable history versions return 404. The LangChain tool returns the corresponding `{ "ok": false, "error": "..." }` contract instead of raising into the agent loop. API and tool calls share one process-wide `KnowledgeWiki` runtime.

## Source-aware examples

Content-only ingestion does not need a Library file:

```json
{
  "title": "Compounding Knowledge",
  "content": "The maintained synthesis supplied by the caller.",
  "source_trust": "user_supplied",
  "provenance": [{"kind": "interview", "ref": "user-supplied-notes"}]
}
```

Path ingestion is explicit:

```json
{
  "source_path": "Library/Research/article.md",
  "approved_source": true,
  "title": "Article Synthesis",
  "content": "The complete revised synthesis to maintain in Knowledge."
}
```

The second example is the only workflow that reads that path. It is not a general Library sync.

## Source

Pattern adapted from [Andrej Karpathy's LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94e).
