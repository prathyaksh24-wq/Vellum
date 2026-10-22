# Google embedding cutover — 2026-10-20

Follow-up: the [2026-10-21 retrieval and original-checkpoint comparison](embedding-retrieval-2026-10-21.md)
records the subsequent real-model, pipeline and frontend evaluation. The limits
below describe the migration-day work only.

## Implemented and applied locally

- Installed `embeddinggemma-2:270m-q8_0-text` in existing Ollama 0.40.6:
  303,957,438 bytes, manifest
  `c21dd30c1e38444d3b4faa091407b6fa97221447b4965d74931d43d7f09bbbfd`.
- Replaced BGE's 1024-dimensional RAG projection with Google's normalized
  768-dimensional projection. Added explicit query/document prefixes, bounded
  local batching, exact-model checks, and Chroma generation metadata.
- Rebuilt one active Book materialization: **87 chunks**, now 768 dimensions.
  Readback confirmed its model and `retrieval-prefix-v1` revision. The old BGE
  index and old publication artifacts remain available.
- Kept `ENABLE_VECTOR_SEARCH=false`; the empty vault and saved-query collections
  stayed empty. This did not index the remaining vault documents.
- Backed up PostgreSQL with `pg_dump -Fc` and inspected the archive table of
  contents with `pg_restore --list`. Rebuilt **432 Honcho document vectors** and
  **402 message vectors** in one transaction using the existing Honcho client.
  Readback reported min/max dimensions 768 and zero null vectors in both tables.
- Activated Google in the running Honcho container, read back its model setting,
  and restarted the deriver. Retained its symmetric unprefixed embedding contract
  separately from RAG's prefixed vector space.
- Updated skills catalog cache identity so unchanged text cannot reuse a vector
  from another model revision. Current catalog and learning DBs had zero vectors;
  no skill-vector migration or additional private-source indexing was needed.

## Service readiness and static checks

- Vellum `/api/health`: HTTP 200 after final backend restart.
- Honcho `/health`: HTTP 200; Compose reported API, PostgreSQL and Redis healthy,
  with the deriver running.
- Served Vellum frontend document on port 5173: HTTP 200.
- Python AST parsing: nine changed/new Python modules parsed successfully.
- PowerShell static parsing: `scripts/start-honcho.ps1` parsed successfully.
- Task-scoped `git diff --check`: no whitespace errors; Git reported existing
  LF-to-CRLF checkout notices for several files.

An old Vellum diagnostic API was occupying Honcho's port 8001. Its exact
`uvicorn agent.api:app --port 8001 --lifespan off` command was identified before
stopping it. The regular Vellum API remains on port 8000.

The first Honcho maintenance invocation failed before importing its application
package. Adding `/app` to the mounted script's module path fixed the import;
the rerun completed. The original validated backup was preserved across retries.

## Local receipts and recovery

Machine-owned receipts remain ignored, outside the Git change:

- `data/embeddings/migration-20261020T122915Z/receipt.json` and its settings,
  Chroma and Knowledge Core snapshots.
- `data/embeddings/honcho-migration-20261020/postgres-before.dump`, archive
  contents and content-free migration log.
- `data/embeddings/google-embedding-readback-20261020.json` with active model,
  index counts/revisions, installed digest and HTTP statuses.

Settings snapshots contain credentials and must remain local. See
[migration and rollback instructions](../architecture/local-embeddings.md).

## Verification limits

No automated tests were added or run. No frontend chat flow, representative
retrieval-quality evaluation, semantic-threshold calibration, OCR flow or
long-session performance comparison was performed. The migration executed real
local embedding inference for all 921 rebuilt vectors; this demonstrates model
execution and projection replacement, not improved answer quality. Existing
score thresholds remain unchanged. Old nomic and BGE model files are retained
for recovery rather than removed automatically.
