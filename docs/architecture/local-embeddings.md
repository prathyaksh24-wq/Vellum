# Local embedding model and migration

## Runtime and ownership

Vellum's shared `agent.rag.embedder.get_embedder()` uses the existing Ollama
service. The default model is Google's EmbeddingGemma 2 text-only 270M model,
quantized as `embeddinggemma-2:270m-q8_0-text`. The installed manifest is pinned:

```text
c21dd30c1e38444d3b4faa091407b6fa97221447b4965d74931d43d7f09bbbfd
```

Vectors have 768 normalized components. Input is bounded by the model's
documented 8,192-token context, including the retrieval prefix. Requests set
`truncate=false` so oversized input fails rather than silently losing text.
This embedding budget is separate from the chat model's context budget.

The text package is about 304 MB. It does not add OCR, image parsing or audio
extraction. See the [primary-source research](../research/google-embeddinggemma-2-2026-10-20.md).

No additional model server, cloud embedding provider or download-on-request
fallback is introduced. Host requests require a loopback Ollama URL and ignore
proxy environment variables. Batches are serialized and bounded (default 16).
The model digest is checked before each RAG operation. Do not replace the model
tag during a running migration or service operation.

## Embedding contracts

| Consumer | Contract | Storage |
| --- | --- | --- |
| Vault and Books queries | `task: search result \| query: {query}` | Compare only with the matching RAG generation |
| Vault, Books and skill documents | `title: none \| text: {text}` | Chroma or the existing skills catalog |
| Optional saved query vectors | Query prefix | Existing `agent_queries` collection |
| Honcho queries and documents | Unprefixed text, symmetric | Existing PostgreSQL pgvector tables |

Honcho's pinned upstream client does not expose separate query/document
prefixes. Its existing unprefixed transport is retained consistently during
both rebuild and runtime. RAG's prefixed and Honcho's unprefixed vectors are
separate spaces even though their dimensions and model weights match. Honcho
retrieval quality with this contract has not been benchmarked.

Chroma metadata identifies backend, model, revision, prompt profile and width.
Unknown or mismatched collections are rejected. Books carry the provider
revision into materialization identity and compatibility filtering. Skill
catalog vector reuse requires matching text and embedding profile; metadata-only
reconciliation discards incompatible vectors without invoking a model.
Existing semantic-score thresholds are unchanged and require later calibration
against representative user queries.

## Settings

| Setting | Default |
| --- | --- |
| `EMBEDDING_BACKEND` | `ollama` |
| `EMBEDDING_MODEL` | `embeddinggemma-2:270m-q8_0-text` |
| `EMBEDDING_MODEL_REVISION` | Full manifest digest above |
| `EMBEDDING_DIMENSIONS` | `768` |
| `EMBEDDING_BATCH_SIZE` | `16` |
| `EMBEDDING_TIMEOUT_SECONDS` | `90` |
| `CHROMA_PATH` | `data/embeddings/chroma-embeddinggemma2-v1` |
| `HONCHO_EMBEDDING_MODEL` | Legacy nomic until explicitly migrated |

`ENABLE_VECTOR_SEARCH` and query storage retain their existing values. Changing
the model does not index additional private sources or enable vector search.
FTS5, transcripts, canonical memory and source imports remain under their
existing owners. Fresh Honcho installations may explicitly select Google;
existing volumes must complete migration before changing this setting.

## Existing RAG/Books installation

1. Install a supported Ollama runtime and pull the exact text tag. The migration
   checks its manifest digest before publishing anything.
2. Stop Vellum's API and any separate vault watcher/index writer. Run from the
   canonical checkout with its virtual environment:

   ```powershell
   .\.venv\Scripts\python.exe scripts/migrate_local_embeddings.py --apply
   ```

3. The tool requires the old index and an empty, separate target. Override
   `--source-path` and `--target-path` for a nondefault installation. It backs
   up settings, Chroma and Knowledge Core locally, rebuilds only previously
   indexed vault paths and query vectors, and rematerializes active Books from
   original sources through the existing book pipeline.
4. Only after all projections succeed does it atomically switch the five RAG
   settings. Failure restores the previous active-book pointers and leaves
   settings unchanged. New inactive artifacts remain inspectable. Restart the API.

Backups and content-free migration receipts are under ignored
`data/embeddings/migration-<UTC timestamp>`. The settings backup contains secrets
and must remain local. The old original index and model weights are retained.

## Existing Honcho installation

Honcho uses a pinned upstream image and two vector tables: `documents` and
`message_embeddings`. `configure_embeddings.py --yes` adjusts dimensions only;
it cannot replace nomic vectors with Google vectors at the same width.

1. Stop `honcho` and `honcho-deriver`; leave PostgreSQL and Redis running.
2. Save a local `pg_dump -Fc` archive and validate its table of contents with
   `pg_restore --list`. Retain the original model configuration until success.
3. Mount `scripts/migrate_honcho_embeddings.py` read-only in a one-off
   `honcho-configure` container. Use the image's Python, set only this container's
   embedding model to the exact Google tag, and pass `--apply`:

   ```powershell
   $migrationFile = (Resolve-Path scripts/migrate_honcho_embeddings.py).Path
   docker compose run --rm --no-deps -T --entrypoint /app/.venv/bin/python `
     -e EMBEDDING_MODEL_CONFIG__MODEL=embeddinggemma-2:270m-q8_0-text `
     -v "${migrationFile}:/tmp/migrate_honcho_embeddings.py:ro" `
     honcho-configure /tmp/migrate_honcho_embeddings.py --apply
   ```

4. The script checks the local model digest and 768-dimensional configuration,
   locks both tables, rebuilds every row from retained text using Honcho's own
   embedding client, and commits both tables in one transaction. IDs, canonical
   text, scopes and provenance stay intact. A conservative 8,000-byte per-input
   guard aborts before commit for content requiring a more specific migration.
   This maintenance tool supports the current pgvector deployment; it does not
   migrate an external vector-store replica.
5. After the complete receipt, set `HONCHO_EMBEDDING_MODEL` in local `.env` to
   the Google tag and run `scripts/start-honcho.ps1`. Startup verifies the local
   model digest, and Compose recreates API/deriver with matching settings.

Never run the maintenance script with active readers/writers or switch back to
nomic against already-migrated Google vectors. Same width is not compatibility.

## Book retrieval compiler

Book compiler `book-to-skill-v1.3.0-vellum.3` uses a 1,600-character target
for complete source blocks; an indivisible larger block remains intact. Routine
retrieval keeps the existing 2,400-token limit, combines up to 48 semantic
candidates with BM25 ranks over validated active chunks, and preserves tenant,
named-title, destination, digest and citation checks. Presentation directions
after a question do not alter its search embedding; synthesis and receipts keep
the original request. Existing Book assets and previous materializations remain
available for recovery; rebuilding publishes a new derived materialization.

The optional full-precision evaluation checkpoint and its isolated Python
environment are not runtime dependencies. They were removed after the Q8
comparison; metrics remain locally under the ignored evaluation directory.

## Rollback

Stop all affected writers before rollback. For RAG, restore the prior model
settings and old Chroma path together, and restore the original active-book
publication pointers from the Knowledge Core snapshot. Do not blindly overwrite
a live canonical database containing newer user data. Legacy BGE rollback uses
`sentence_transformers`, `BAAI/bge-m3`, revision `default`, and 1024 dimensions.
Untagged legacy BGE collections are accepted only in that explicit legacy mode.

For Honcho, either restore the validated PostgreSQL snapshot together with the
old nomic model setting before accepting new writes, or re-embed current rows
through a reviewed reverse migration. Restoring a snapshot after subsequent
memory writes loses those newer records; preserve them before considering it.
