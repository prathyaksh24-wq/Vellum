# Vellum Knowledge Wiki

Vellum's Obsidian knowledge layer follows the persistent LLM-wiki pattern described by Andrej Karpathy. It complements the Memory Orchestrator rather than replacing it.

## Layers

```text
Vault/
|-- Library/                 Immutable raw sources
|-- Knowledge/               Vellum-maintained linked synthesis
|   |-- index.md             Content map; always queried first
|   |-- overview.md          High-level synthesis
|   |-- schema.md            Ingest/query/lint contract
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

`Library/` is immutable to the wiki service. Only `Knowledge/` is written by the wiki service. `Agent/Memories/` remains the durable personal-memory layer.

## Page contract

Content pages have a stable ID, page type, title, description, sensitivity, lifecycle status, timestamps, version, sources, source count, and tags. Page types are `source`, `entity`, `concept`, `topic`, `project`, and `analysis`.

Sensitivity is explicit:

- `public` preserves public entity names.
- `private` applies local deterministic scrubbing to model-facing maps and page reads.
- Missing sensitivity defaults to `private`.

Updates replace the maintained synthesis, save the previous page under `.history/`, rebuild `index.md`, and append to `log.md`. Raw source files are never changed.

## Agent workflow

1. `knowledge_wiki(action="query")` reads the index and returns a small map with opaque page references.
2. `knowledge_wiki(action="read_page")` reads only the selected references.
3. `knowledge_wiki(action="ingest_source")` compiles one `Library/` source and complete revisions for related pages.
4. `knowledge_wiki(action="update_overview")` refreshes the high-level synthesis.
5. `knowledge_wiki(action="lint")` reports schema gaps, missing sources, broken links, duplicate titles, orphan pages, stale pages, and overview drift. It never deletes or rewrites content.

## API

The stable API lives under `/api/knowledge`:

- `GET /status`
- `GET /query?q=...&limit=8`
- `GET /pages/{page_ref}`
- `POST /pages`
- `POST /ingest`
- `POST /overview`
- `POST /lint`
- `POST /rebuild-index`

The API and LangChain tool share one process-wide `KnowledgeWiki` runtime.

## Source

Pattern adapted from [Andrej Karpathy's LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
