# EmbeddingGemma 2 integration facts

Verified against primary sources on 2026-10-20. This note records research; it does not prove a local model installation or migration.

## Model identity and supported shape

The exact requested model exists: `google/embeddinggemma-2`, Apache 2.0. The inspected Hugging Face revision is `914f7f89142e33e77833254d9c9b90c3cef7303b`. Its full multimodal checkpoint is 740M parameters; text-only execution uses 270M. Native output is 768 dimensions, with supported 512/256/128-dimensional prefixes that require normalization after truncation. Use Google's documented 8,192-token input budget despite larger architectural position metadata. FP32 or BF16 is required for the original floating-point model; Google warns that FP16 can silently produce invalid vectors. [Model card](https://huggingface.co/google/embeddinggemma-2), [pinned revision](https://huggingface.co/google/embeddinggemma-2/commit/914f7f89142e33e77833254d9c9b90c3cef7303b).

## Preferred Windows deployment

Use the existing local Ollama service with the explicit portable text tag `embeddinggemma-2:270m-q8_0-text`, listed as a 304 MB Q8_0 `gemma-embedding2` model. Its inspected manifest prefix is `c21dd30c1e38`; the weight blob prefix is `111e84992a04`. Record the full installed digest at cutover. Avoid choosing an MLX-only tag for Windows. [Official tag](https://ollama.com/library/embeddinggemma-2:270m-q8_0-text), [GGUF metadata](https://ollama.com/library/embeddinggemma-2:270m-q8_0-text/blobs/111e84992a04), [all tags](https://ollama.com/library/embeddinggemma-2/tags).

Ollama merged native llama.cpp support for EmbeddingGemma 2 in PR #18917; the v0.40.4 release includes the corresponding embedding runner changes. Recommend current stable Ollama at least v0.40.4, then require actual installed-model capability checks before switching. This is a deployment recommendation rather than a guarantee about every earlier runtime. [Merged implementation](https://github.com/ollama/ollama/pull/18917), [v0.40.4 release](https://github.com/ollama/ollama/releases/tag/v0.40.4).

Keep 768 output dimensions initially. Set the embedding input limit to 8,192 rather than accepting the library's 256K metadata as a quality guarantee. Text-only installation does not enable image/audio/video extraction or retrieval in Vellum.

## Prompt contract

Google ships these exact retrieval prefixes:

- Query: `task: search result | query: `
- Untitled document: `title: none | text: `
- Titled document: `title: {title} | text: {content}`

The Sentence Transformers configuration has `default_prompt_name: null`. Thus plain `encode()` supplies no automatic task prefix; `encode_query()` and `encode_document()` select the corresponding named prompts. [Official prompt configuration](https://huggingface.co/google/embeddinggemma-2/raw/main/config_sentence_transformers.json), [Transformers usage](https://huggingface.co/docs/transformers/main/model_doc/embedding_gemma2).

Ollama's inspected `/api/embed` implementation passes supplied text through tokenization to `r.Embedding` without choosing a retrieval role or applying these prefixes. The caller must format them once. Its handler normalizes the resulting vector and rejects nonfinite values. A generic OpenAI-compatible embeddings consumer cannot be assumed to distinguish query and document roles: inspect its caller before selecting a prompt contract. [Pinned Ollama handler, especially EmbedHandler](https://raw.githubusercontent.com/ollama/ollama/v0.40.4/server/routes.go).

## Sentence Transformers alternative

The officially required Sentence Transformers version is `>=6.1.0`. The inspected checkpoint records Transformers `5.18.0.dev0`, but that build metadata does not establish the first supported stable release. Current main documentation names stable `5.20.2`; exact minimum stable Transformers support was not established in this research. A runtime must recognize `embedding_gemma2` before use. [Checkpoint requirements](https://huggingface.co/google/embeddinggemma-2/raw/main/config_sentence_transformers.json), [Transformers documentation](https://huggingface.co/docs/transformers/main/model_doc/embedding_gemma2).

For text only, Google documents `config_kwargs={"vision_config": None, "audio_config": None}`. This avoids loading unused encoders into RAM. The repository has one approximately 1.49 GB `model.safetensors` file, so encoder omission must not be advertised as avoiding the full checkpoint download. [Developer guide](https://developers.googleblog.com/embeddinggemma-2-the-developer-guide/), [checkpoint files](https://huggingface.co/google/embeddinggemma-2/tree/main).

## Vellum migration recommendation

Prefer one Ollama runtime for Vellum RAG and the existing Honcho OpenAI-compatible embedding consumer, provided each consumer's prompt semantics are explicit. Treat provider, model digest, dimensions, normalization, input policy and prompt contract as the embedding-space identity. Rebuild existing indexes into a new generation; do not compare old-model vectors with new-model vectors even when both happen to have 768 dimensions. Preserve original source records and the old index until cutover is complete. Whether existing Honcho data can be re-embedded safely needs a separate inspection of its canonical migration/embedding paths.

## Honcho deployment inspection

The Vellum Compose source pins Honcho `93dcf59c4a4225bb020b20c628799737fefae318`. At that revision, embedding configuration exposes transport, model, credentials/base URL, dimensions policy and batching, but no query/document prefix settings. Both `embed(query)` and batch paths pass their text unchanged into OpenAI-compatible embeddings. Therefore environment configuration alone cannot add asymmetric Google prefixes to stock Honcho. One compatible option is a separately identified unprefixed embedding contract for Honcho; alternatively, extend its existing canonical embedding client after auditing call-site roles. Do not introduce a new proxy just to guess roles. [Pinned config](https://raw.githubusercontent.com/plastic-labs/honcho/93dcf59c4a4225bb020b20c628799737fefae318/src/config.py), [pinned embedding client](https://raw.githubusercontent.com/plastic-labs/honcho/93dcf59c4a4225bb020b20c628799737fefae318/src/embedding_client.py).

The pinned `scripts/configure_embeddings.py`, fetched through the GitHub connector after the web reader failed, only adjusts vector column dimensions. At equal dimensions it skips alteration; when dimensions differ it refuses non-null embeddings. It does not re-embed records or schedule migration. In particular, switching 768-dimensional nomic vectors to 768-dimensional Google vectors is not made safe by running `configure_embeddings.py --yes`. [Pinned bootstrap script](https://github.com/plastic-labs/honcho/blob/93dcf59c4a4225bb020b20c628799737fefae318/scripts/configure_embeddings.py).

The vector columns are `documents.embedding` and `message_embeddings.embedding`. Both retain text content and scope/provenance fields. The message row refers to `messages.public_id`; document rows retain `source_ids`, observer, observed and workspace. `sync_state`, `last_sync_at` and `sync_attempts` track synchronization rather than embedding-model identity. [Pinned models](https://github.com/plastic-labs/honcho/blob/93dcf59c4a4225bb020b20c628799737fefae318/src/models.py).

The official `generate_message_embeddings.py` creates vectors only for messages that have no embedding rows. It neither replaces existing rows nor handles documents. The reconciler can re-embed pending message rows whose vectors are null using their preserved content, then persist the vector and synchronized state. However, the pgvector-only reconciliation cycle skips document reconciliation; merely setting both tables to null/pending would leave document vectors missing. [Pinned message script](https://github.com/plastic-labs/honcho/blob/93dcf59c4a4225bb020b20c628799737fefae318/scripts/generate_message_embeddings.py), [pinned reconciliation implementation](https://github.com/plastic-labs/honcho/blob/93dcf59c4a4225bb020b20c628799737fefae318/src/reconciler/sync_vectors.py).

No complete same-dimension replacement command was identified in the pinned scripts or inspected reconciliation paths. A safe migration needs a database backup and readers/writers stopped until every affected vector is rebuilt. It should extend migration tooling using Honcho's existing embedding client and original content, preserve IDs/provenance and fail atomically or retain a restorable old generation. It must handle document vectors explicitly, check token bounds on preserved content, and record the embedding contract. Until such migration completes, keep Honcho on its prior model rather than mixing vector spaces.

No model installation, local inference, tests, or code changes were performed by this research task. Agent Reach's Jina Reader route returned no content in this environment; sources were verified through the available web reader against official model/runtime documentation and source code.
