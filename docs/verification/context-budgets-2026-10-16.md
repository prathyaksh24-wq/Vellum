# Context budgets and compaction — 16 October 2026

This records the initial extractive-budget phase in the original working tree.
The subsequent [context-management report](context-management-2026-10-16.md)
covers optional local semantic summaries, manual compaction, and source recall.
Tests were not rerun when preparing the isolated draft PR, at the user's request.

## Delivered behavior

- Main reasoning requests use a 32,768-token ceiling; specialist model calls use
  16,384. Model limits, the local transport ceiling, and smaller profile overrides
  can narrow those budgets.
- Prompt accounting includes instructions, skills, memory, history, tool schemas,
  tool-call arguments, generation reserve and a safety margin. Reasoning modes
  reserve their scaled output allowance.
- Older conversation turns compact into attributed, incomplete local excerpts
  persisted in the existing LangGraph checkpoint. No extra model call, summary
  database, cloud disclosure or durable-preference write is introduced.
- Complete older read rounds within one long task can compact too. The current
  user request, latest read rounds, mutation evidence and pending/parallel tool
  batches remain intact. Oversized protected material produces an actionable
  error before inference; the non-streaming API uses HTTP 422.
- Canonical conversations remain intact; graph rebuilds reload the digest.
- The existing frontend stream receives a completed context-compaction activity.

Implementation details and configuration are documented in
[Context budgets](../architecture/context-budgets.md).

## Automated verification

- Final context/routing/profile/graph/provider/config regression set: **184
  passed**, one existing Starlette/AnyIO deprecation warning.
- Complete affected API/streaming/disclosure/privacy/provider/config set:
  **154 passed**, one existing Starlette/AnyIO deprecation warning. The initial
  run found two outdated model-factory test stubs; they now accept and verify
  the explicit main-agent role. The complete rerun passed in 128.71 seconds.
- Affected frontend streaming/conversation suites: **45 passed** across three
  files. This includes the new compaction-event metadata/answer-stream check.
- Frontend production build: **passed**. Vite reports the existing classic-script
  bundling warnings; the output still relies on the repository's static-asset
  copy step. No claim of full browser behavior follows from the build alone.
- `git diff --check`: passed, with Windows LF/CRLF conversion warnings.

The focused tests cover role and model caps, smaller fallbacks, generation
reservation enforcement, repeated compaction, valid large current requests,
overflow, disabled compaction, parallel call/result pairing, closed read-round
compaction, mutation preservation, attachment envelopes, checkpoint resume,
short follow-ups, and the actionable HTTP error.

Windows sandbox execution could not create asyncio's internal loopback socket.
Async verification ran successfully outside that sandbox using a writable
`--basetemp`. This was an execution-environment issue, not a passing test result.

## Live served-frontend checks

The opt-in `scripts/verify-context-budget-frontend.py` used the actual served
Vellum frontend, real local `ollama/gemma4:12b`, an isolated API, a muted disposable
Edge browser, and synthetic conversations/memory under `.scratch`. Unrelated
connector health discovery was stubbed; chat requests and inference were live.
No public post was published.

| Check | Observed result |
| --- | --- |
| Long conversation exceeding the main budget | Estimated input reduced from **35,448 to 16,799 tokens**; 28 old checkpoint messages removed into the digest |
| Fact retention | Invitation preserved **23 November 2026** and **Kochi** from the first synthetic user message |
| Page reload and checkpoint reopening | A shorter follow-up invitation retained the same date/city after closing cached graphs and reopening SQLite state |
| Source preservation | Original 40 source messages remained; the saved UI conversation contained 44 messages after two additional exchanges |
| Main model transport | Actual Ollama `num_ctx=32768` observed |
| Specialist transport | Actual XAgent Ollama `num_ctx=16384` observed |
| Browser JavaScript errors | None in the recorded successful context runs |
| Hardware residency | `ollama ps` reported Gemma 4 at **32,768 context, 8.1 GB, 100% GPU** on this laptop |

The final main-only run took **47.45 s** and **39.27 s** for its two replies.
An earlier run took **12.62 s** and **14.26 s**. These are observations under
different runtime load/cache conditions, not a latency benchmark or improvement
claim. Increasing context does not guarantee faster generation.

Local evidence:

- Main/reload verification:
  `.scratch/context-budget-live-c7265f77e9/evidence.json`.
- Specialist transport observation and failed task:
  `.scratch/context-budget-live-2c0580d5b8/evidence.json`.

## Remaining limits and failed specialist tasks

- **The X draft task failed.** It reached a 16k specialist model request but timed
  out and ultimately returned an irrelevant no-source-evidence answer after
  181.13 s. The context transport check passed; X task completion did not. This
  work does not claim to repair X intent handling, posting or timeouts.
- A separate Sports definition probe used its deterministic path, made no
  specialist model call, and returned raw search data. It cannot demonstrate a
  specialist context window or successful sports answer formatting.
- Excerpt selection is lossy, and the byte-based token estimate is not an exact
  provider tokenizer. Arbitrary multilingual/multimodal inputs and sustained
  parallel-agent latency have not been exhaustively validated.
- The whole backend/frontend repository suites were not run. The listed affected
  suites and live checks define the scope of this verification.

## Runtime and Git status

The local backend was restarted with the implementation; `/api/health` returned
`ok=true`. The served frontend returned HTTP 200. Changes remain in the working
tree alongside unrelated ongoing work. No commit, push, branch or GitHub PR was
created for this task.

## Proposed draft PR

**Title:** Add role-based context budgets and persistent conversation compaction

**Description:** Vellum previously supplied one 16k Ollama setting while the
reasoning checkpoint grew without compaction. This change gives the main agent
32k and specialists 16k, accounts for tools and generation space at each routing
destination, and compacts older evidence in the existing checkpoint while keeping
canonical chat history and mutation boundaries intact. It adds a frontend stream
activity, configurable limits, regression coverage and an isolated live Gemma 4
frontend verifier. Verification and the unresolved X/Sports task-quality and
latency limits are documented above. Compaction uses bounded local excerpts and
approximate token accounting; it does not introduce semantic model summarization
or promise perfect recall.
