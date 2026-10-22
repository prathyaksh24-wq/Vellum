# Embedding retrieval and answer evaluation — 2026-10-21

## Conclusion

No reduction in top-one or top-five retrieval hit rate was measured for the
installed Google Q8 model relative to the original Google checkpoint on this
28-question evaluation. Both returned the same top-one result for every question.
This supports keeping Q8 on the current installation; it does not establish
lossless quantization or reliable answers across Vellum.

The live application still failed a grounded Book answer and misrouted a
historical-memory question. A traced Book retrieval check showed useful passages
being discarded during evidence selection. Replacing Q8 with the original
weights is not supported as a remedy for these failures by this evaluation.

Final readiness: Vellum API, Honcho and the served frontend were restored through
the existing startup scripts and returned HTTP 200. Both embedding settings
remain on Q8. The vault vector-search setting remains disabled.

## Models and execution

| | Installed Q8 | Original checkpoint |
| --- | --- | --- |
| Identity | `embeddinggemma-2:270m-q8_0-text` | `google/embeddinggemma-2` |
| Artifact bytes | 303,957,438 | 1,488,915,288 |
| Runtime | Ollama 0.40.7 (final readback) | Transformers 5.20.2 / PyTorch 2.14.0+cpu |
| Execution | Ollama GPU offload | CPU, FP32, four PyTorch threads |
| Text parameters | 270M class | 271,002,624 loaded parameters |
| Output width | 768, normalized | 768, normalized |
| Document batch | 4 | 4 |

Q8 manifest:
`c21dd30c1e38444d3b4faa091407b6fa97221447b4965d74931d43d7f09bbbfd`.

Original Hugging Face revision:
`914f7f89142e33e77833254d9c9b90c3cef7303b`.

Original `model.safetensors` SHA-256, checked after download:
`197a32965d4b1105faf060417baa899e193fb73cd401f42ec9295234d5553d79`.

The original 1.49 GB checkpoint includes vision/audio weights. This evaluation
loaded its unquantized text path and disabled unused vision/audio encoders, as
Google documents for text-only execution. It did not test multimodal retrieval.
The original was evaluated in a separate local environment; Vellum's installed
dependencies, model settings and active index were not replaced.

The Ollama BF16 text tag could not be pulled because that artifact requires MLX
on this runtime. The comparison therefore used the actual original Google
checkpoint, not another Q8 artifact. CPU FP32 follows Google's precision guidance.
See [Google's model card](https://huggingface.co/google/embeddinggemma-2) and
[the installed Ollama artifact](https://ollama.com/library/embeddinggemma-2:270m-q8_0-text).

## Evaluation method

- Reused all **87 existing Meditations chunks** and **171 Honcho documents**
  scoped to the `default` observer/observed peer. Assistant-peer documents were
  excluded from the personal-memory comparison.
- Fixed **16 Book questions** and **12 memory questions**, with manually selected
  primary evidence IDs, before running either model. Book cases included factual
  questions, paraphrases, one spelling-error case and one Hindi question.
- Embedded the same text for each variant. Books used Google's search-query and
  untitled-document prefixes; memory used Honcho's current symmetric unprefixed
  contract. Inputs were not truncated; both retained 768 output dimensions.
- Ranked by exact normalized dot product. A hit means at least one annotated
  primary evidence item appeared within the first k results. This is a hit rate,
  not the fraction of all relevant passages retrieved, and not answer accuracy.
- Recorded per-query timing and five repeated requests per corpus. Separately
  exercised Vellum's real Book pipeline with its active Q8 index, citation checks,
  hybrid ranking, six-chunk limit and 2,400-token evidence budget.
- Checked four frontend outcomes with local Gemma 4 before the user requested
  continuation without computer use. All subsequent work used terminal checks
  and saved results; no further computer use was performed.

## Paired retrieval results

| Metric | Q8 | Original |
| --- | ---: | ---: |
| Book primary evidence at rank 1 | 8/16 (50%) | 8/16 (50%) |
| Book primary evidence in top 3 | 10/16 (62.5%) | 10/16 (62.5%) |
| Book primary evidence in top 5 | 10/16 (62.5%) | 10/16 (62.5%) |
| Memory primary evidence at rank 1 | 10/12 (83.3%) | 10/12 (83.3%) |
| Memory primary evidence in top 3 | 11/12 (91.7%) | 11/12 (91.7%) |
| Memory primary evidence in top 5 | 12/12 (100%) | 12/12 (100%) |

Fourteen of 16 Book questions and 11 of 12 memory questions had identical
top-five result sets. Other sets changed non-primary neighbors without changing
top-one results or hit rates. Primary-rank differences were two Book misses:
revenge moved from rank 17 in Q8 to 16 in the original, and the right/true rule
moved from rank 33 to 32. Neither change affected the top-five hit rate.

Mean paired cosine similarity:

| Vector group | Mean | Minimum |
| --- | ---: | ---: |
| Book documents | 0.999840 | 0.999536 |
| Book queries | 0.999874 | 0.999723 |
| Memory documents | 0.999779 | 0.999275 |
| Memory queries | 0.999832 | 0.999739 |

Cosine similarity describes vector agreement, not a percentage of answer
accuracy. All generated document vectors were finite, nonzero, 768-dimensional
and normalized. Repeated-query cosine agreement was approximately 1.0 in both
variants. The initial Q8 run matched migrated stored memory vectors with minimum
cosine 0.99999988; the final runtime-refresh run's minimum was 0.999475. This
also shows small numerical differences can exist across runtime executions.

## Observed performance

| Measurement | Q8 | Original |
| --- | ---: | ---: |
| Warm Book query median | 21 ms | 149 ms |
| Warm Book query p95 | 31 ms | 166 ms |
| Warm memory query median | 20 ms | 110 ms |
| Warm memory query p95 | 26 ms | 125 ms |
| Encode the 87 Book documents | 4.0 s | 489.4 s |
| Encode the 171 memory documents | 3.1 s | 16.6 s |

These are observations of different backends and devices, not a controlled
quantization-speed comparison. Q8's timings include local HTTP transport;
the original used in-process CPU inference. The machine was an AMD Ryzen 9
8940HX with an RTX 5070 Ti Laptop GPU (12,227 MiB). Development services were
running. These are single-run local results, not idle-machine or long-session
benchmarks. Loading and warming were measured separately from the query table.

The final Q8 run was refreshed after reading the actual Ollama version, 0.40.7;
the original harness had carried an assumed version string from setup notes.
An earlier Q8 run under the development workload observed 151/140 ms query
medians and 57.6/21.1 s corpus encoding. That earlier run's actual runtime version
was not captured. Do not attribute the speed difference solely to a version
upgrade or compare the two phases as a controlled performance experiment.

Q8's sampled Ollama resident size was 380,496,772 bytes, all reported in VRAM,
with context 8,192. The original evaluation process peaked at 2,643,537,920 bytes
RSS. These measures cover different memory owners and must not be compared as a
like-for-like total-memory ratio. Artifact size also differs because the
original download includes unused modality encoders.

## Vellum pipeline findings

### Book evidence is dropped after candidate retrieval

The actual Chroma candidate lists contained annotated primary evidence for
**15/16 questions**. The final source-validated evidence packet contained it for
**8/16**. A passive reproduction of the existing hybrid-score and token-budget
selection produced exactly the same selected chunks as the live pipeline on
all 16 cases.

In seven cases, a primary passage was present but not selected. In four of these
it ranked second after hybrid scoring, yet did not fit after the first selected
chunk. Existing chunk lengths range from 6 to 5,986 characters, with a median of
5,457 characters. A 2,400-token whole-chunk budget often accommodates only one
long passage plus short fragments. Smaller source chunks and better selection
should be investigated while preserving whole-chunk provenance and citations.

The real pipeline's median retrieval duration was **2.70 s**, with the first
observed request taking 15.10 s. A wrong-tenant probe returned zero evidence.
That single probe is not a comprehensive access-control audit.

### Grounded Book answer failed

The frontend asked what Marcus says when one struggles to get out of bed. It
delegated to BooksAgent and queried Book evidence, but after **142 s** displayed:
“I retrieved the book passages, but could not produce a validated summary.”
This is a synthesis/integration failure, not a successful answer. A captured
backend trace entered `RoutedBooksSynthesizer` and showed a cancelled request;
the synthesizer has a 60-second routed request timeout. More investigation is
needed to attribute the precise cancellation and retry behavior.

As a separate capability baseline, the same `gemma4:12b` model, given the correct
passage and a small two-sentence prompt with thinking disabled, returned a
source-supported answer in **1.53 s** (414 prompt tokens, 37 output tokens).
This differs from Vellum's structured synthesis prompt and generation settings;
it demonstrates generation capability, not a repaired frontend flow.

### Historical memory question was misrouted

“Which web browser have I used before? Use my saved conversations or memory as
evidence…” opened BrowserAgent and invoked browser session tools. The evaluator
stopped it after 75 s and closed the panel it opened. It did not supply the
expected memory answer. The corresponding scoped Honcho vector retrieval placed
the relevant browser entry first in both embedding variants.

A read-only FTS5 screen found the expected answer term in the first five results
for 7/12 memory questions, at a median 4.3 ms. This was keyword screening only,
not manual evidence grading or a comparison of equivalent stores. Main-agent
memory assembly also uses FTS5, saved memories and cached portraits; a successful
Honcho-vector benchmark does not establish that those paths are used correctly.

### Short-term context was correct but slow

The frontend repeated a temporary demonstration label correctly, then recalled
the exact label on the following turn. UI activity durations were **101 s** and
**136 s**. This supports one simple context-continuity case, not long-term or
cross-chat memory reliability. A minimal direct-model label request was correct
in 14.22 s, including 13.85 s of model loading; prompt processing and generation
were about 0.18 s each.

## Focused automated checks

- `backend/tests/test_rag.py` and `test_vault_search_logging.py`: **8 passed**
  in 24.78 s.
- `backend/tests/test_books_agent.py`: **23 passed** in 80.64 s.

These checks use controlled fixtures and do not establish retrieval quality or
real-model answer reliability. The live failures above remain failures despite
the 31 passing tests.

## Limits and retained artifacts

This is a small local evaluation: one book and existing derived memory entries,
with manually annotated primary evidence rather than exhaustive relevance
judgments. Memory retrieval was graded against stored entries, not independent
verification of their truth. No original-model frontend A/B, broad multilingual,
OCR, multimodal, sustained-load or full regression suite was run. Runtime and
conversion differences mean this compares two deployed model paths, not an
isolated mathematical quantization ablation.

An initial API answer-check batch encountered a transient closed connection
during a development server restart. Those four attempts are not counted as
model-quality outcomes. The earlier original-model run was interrupted before
results were saved; the resumed complete run exited successfully.

Private corpus copies, vectors, per-case metrics, screenshots and receipts remain
ignored under `data/embeddings/evaluation-20261021/`. The original checkpoint is
under ignored `data/models/embeddinggemma2-reference/`. Evaluation tools and the
isolated Python environment are under ignored `.scratch/`. One frontend QA chat
was retained; durable memory was switched off after its first turn. The active
Q8 configuration and production vector generation were not switched, and no Git
publication was performed.

Follow-up: [Q8 retrieval and context repairs](q8-retrieval-repairs-2026-10-22.md)
records the subsequent fixes and repeated checks. At the user's request the
full-precision checkpoint, partial downloads and isolated comparison environment
were removed after this evaluation; its metrics remain local. The artifact
locations above describe what existed during the comparison.
