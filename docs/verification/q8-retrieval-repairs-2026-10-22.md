# Q8 retrieval and context repairs — 2026-10-22

## Outcome

Retained `embeddinggemma-2:270m-q8_0-text` as Vellum's embedding model.
Removed the full-precision comparison checkpoint, partial downloads and its
isolated evaluation environment: **3,301,788,643 bytes** in total. Readback
confirmed both directories absent and only the Q8 EmbeddingGemma tag installed.
The benchmark metrics, canonical Book asset, memory databases, migration backups
and legacy rollback indexes remain local. No Git publication was performed
during those development checks; the publication scope below describes the
subsequently authorized draft PR.

This follows the [original comparison](embedding-retrieval-2026-10-21.md).
The repairs below address pipeline and inference behavior exposed by that work;
they do not change embedding weights or Honcho's vector contract.

## Publication scope

Prepared on `codex/q8-retrieval-repairs` from `origin/main` at `b025cc8`, using a
separate worktree. **No tests, builds, model calls or live checks were rerun for
this publication, as requested.** The results below were recorded earlier in
the development checkout; they do not establish that this isolated PR tree passes.

Only embedding integration/migrations, Book retrieval/synthesis, historical
recall guards, their regression sources and documentation were selected. Current
main's optional personalization adapter in conversation recall is preserved;
unrelated source-presentation, X/YouTube, voice, account and UI changes were
excluded. Main already uses standard non-thinking local inference. This PR
documents and regression-guards that behavior while accepting thinking-capability
metadata without turning it into a request for extra reasoning. The latency
comparison below describes the development checkout, not a new measurement of main.

### Hosted CI follow-up

The initial [CI run 39725214118](https://github.com/prathyaksh24-wq/Vellum/actions/runs/39725214118)
reported **3,321 backend passes, 28 skips and one failure**. The failing
`test_settings_loads_paths_and_privacy_defaults` still expected the legacy
`chroma` directory, while the migration deliberately defaults to the separate
`chroma-embeddinggemma2-v1` generation. Updated that assertion and added explicit
checks for the pinned Q8 model, revision, dimensions, backend and batch size.
Production configuration and the isolated index boundary remain unchanged.

The other five hosted jobs passed: frontend build/tests, Python and frontend
dependency audits, dependency review and secret scanning. No tests or builds
were run locally for this CI correction, respecting the user's instruction.
Those initial hosted results do not establish that the correction has passed;
the subsequent commit's hosted run is the verification owner.

## Changes

- `knowledge/book_materialization.py`: advance the Book compiler to `vellum.3`.
  Target 1,600-character groups of intact source blocks, with larger indivisible
  blocks preserved. Retain whole-chunk budgets, exact hashes, source spans,
  citation validation, tenant scope, active-publication and destination checks.
- Combine up to 48 dense candidates with BM25 ranks from the same validated
  active source chunks. Rank fusion prevents exact names and short maxims from
  disappearing outside dense top-k. A named installed title scopes both paths.
  Presentation directions following the question do not affect its embedding;
  the original request still reaches synthesis and retrieval receipts.
- Rebuilt the installed *Meditations* projection through the canonical
  materialization publisher: **87 → 268 chunks**, 1,814 citation records,
  768-dimensional Q8 embeddings. The source asset was not changed.
- `conversations/recall.py`, `AgentCatalog`, `LiveAgentDispatcher` and
  `BrowserAgent`: keep saved-conversation questions with the main recall owner.
  Guard an incorrectly delegated browser recall request before any browser tool.
  Preserve provider-history requests and new actions referencing an older chat.
  Remove generic answer instructions from keyword relevance matching.
- `BooksAgent`: resolve explicitly named imported titles through the existing
  local Library metadata capability, including wording that omits “book”. This
  closes a live failure where the main model claimed to have checked the text
  without invoking the specialist. No additional registry or data owner was added.
- `OllamaAdapter`: standard turns explicitly disable thinking. Discovery of
  thinking capability alone no longer requests extra inference. Selected
  reasoning modes retain thinking and their output budget; context ceilings are
  unchanged. Book synthesis instructions preserve source qualifications and
  limit unnecessary generalization.

## Verification

**274 focused tests passed**, one existing Starlette/AnyIO deprecation warning,
in 28.70 seconds. Suites:

`test_embedding_retrieval_regressions`, `test_routing_adapters`,
`test_book_documents`, `test_books_agent`, `test_context_management`,
`test_agent_profiles`, `test_delegation_tool`, `test_specialist_agents`,
`test_book_library_api`, and `test_agent_prompt`.

Regressions were reproduced before fixes. Earlier runs exposed outdated compiler,
candidate-count and chunk-count assertions; those now check the new compiler and
actual whole-chunk budget/provenance guarantees. A new two-title test verifies
that removing source boilerplate cannot broaden retrieval to another book.
Existing tamper, cross-tenant, local-only and superseded-materialization checks
remain in the passing suites. Scoped `git diff --check` passed.

| Measured check | Before | After |
| --- | --- | --- |
| Same 16 Book cases: judged primary source region present | 8/16 | 16/16 |
| Full retrieval median | 2.70 s | 0.35 s final run; earlier repeats 0.57–0.76 s |
| Temporary label setup / exact follow-up | 101 / 136 s frontend activity | 27.40 / 9.51 s chat API |
| Morning question synthesis | Failed after 142 s | Completed, source-grounded |

Retrieval timings include validation and index reads. Startup/cache state and
background load vary; these are observed runs, not an isolated speed ablation.
The final run's first retrieval took 1.42 seconds. The source-region metric is
not a claim that every generated answer is correct or that retrieval generalizes
to another corpus.

### Real Gemma 4 chat API checks

Used `ollama/gemma4:12b`, standard reasoning, unique test threads and
`store=false`. No new computer-use or frontend automation was performed.

- Morning question: correctly retrieved Book 5, entry 1 and explained human work
  versus remaining under the blankets. Final answer completed in **43.11 s**.
- Grandfather Verus: character and self-control, **14.09 s**.
- Obstacle/action question: adaptation of obstacles into material for action,
  **27.65 s**.
- Unsupported Python-decorators question: after the title-routing fix,
  **actually invoked BooksAgent** and abstained in **17.54 s**. This supersedes
  the earlier unsupported-topic answers with an empty tool list.
- Context label: correct setup and next-turn recall.
- Browser-memory question: no browser actions; it referenced available historical
  browsing topics and qualified that the browser brand was absent. The current
  canonical archive contains no “Brave” entry. The earlier comparison's derived
  Honcho entry is not independent proof of a surviving original conversation.
  Missing canonical provenance was not bypassed by trusting derived text.

Final Q8 readback returned 768 finite normalized values, norm 1.0. A nonexistent
tenant returned zero Book evidence. Private per-case answers, corpora, receipts
and metrics remain ignored under `data/embeddings/evaluation-20261021/`.

Restored Docker/Honcho and the frontend after finding them stopped. Final HTTP
readback returned **200** for API `/api/health`, Honcho `/health`, and the served
frontend. The backend was restarted with the completed changes.

## Limits

This is a one-book, small-case evaluation, with some ranking decisions informed
by these failures. It is not a held-out retrieval benchmark, a complete memory
recovery audit, a full backend suite, or a new frontend verification. Live Book
generation still took 14–43 seconds; cold/model-context changes and background
load remain relevant. Stronger instructions reduce unsupported generalizations
but do not constitute a semantic entailment verifier. The initial repaired
morning answer contained a generalization about work that the final answer no
longer contained. The main model's summaries of retained chat evidence are not
proof that a historical external action actually happened.

## Proposed PR

**Title:** Repair Q8 Book retrieval, historical recall routing and local reasoning defaults

**Description:** The full-precision comparison showed matching embedding top-1
results but exposed evidence-budget loss, historical questions opening action
agents, and slow structured answers. This change repairs those canonical paths
while retaining Q8, exact Book provenance and existing privacy boundaries.
Smaller versioned chunks and semantic/BM25 fusion improve the local evidence
packet; source-query normalization and installed-title routing ensure ordinary
Book questions reach fresh evidence. Conversation recall wins over domain nouns,
and standard local turns no longer enable thinking merely because it is supported.
Verification comprises the 274-test focused suite and the live Q8/Gemma checks
above. Existing books require the new derived compiler generation; one installed
book was rebuilt locally with old artifacts retained. Remaining limits and
unverified frontend/full-suite behavior are documented above. This description
was prepared before publication; the publication scope above records the final
selection and the user's instruction not to rerun tests.
