# Context budgets and conversation compaction

## Ownership and defaults

The main reasoning agent requests 32,768 context tokens. Specialist planning and
synthesis request 16,384 tokens. These are per-request ceilings, not separate
model copies or a guarantee that every prompt fits. AgentCatalog profiles may
set `context_length` to narrow their specialist budget; it cannot expand the
global specialist ceiling.

Local thinking capability does not enable additional reasoning automatically.
Standard turns send `think=false`; explicitly selected reasoning modes retain
the separate thinking channel and their scaled output reserve. This does not
change the main or specialist context windows.

`agent/llm/context.py` owns prompt accounting and bounded projections.
`RoutingEngine` applies it to every inference destination, including smaller
fallbacks, in both invocation and streaming. `OllamaAdapter` receives the actual
request window as `num_ctx`; invocation options cannot override it or the
reserved generation allowance. Cloud routes retain DisclosureBroker approval
and redaction. The checkpoint projection is local and extractive. Async main-agent
compaction may add a bounded local-model task summary; it never sends a
compaction request to a cloud model.

## Assembly order and authority

`vellum_prompt` assembles one working prompt in this order:

1. Protected instructions, SOUL, runtime clock/permissions,
   specialist directory and activated general skills.
2. Relevant personal evidence from the existing identity and Memory Orchestrator
   owners, bounded to 2,500 and 6,000 characters respectively.
3. Persisted task digest: attributed source excerpts and an optional structured
   local summary of goals, decisions, constraints and open work.
4. Retrieved original conversation evidence, bounded to 4,500 characters.
5. Exact retained messages, including the current user request and tool rounds.

Memory and retrieved history are separate human-role evidence messages carrying
layer metadata, never appended to the protected system prompt or persisted as if
the user had submitted them. Context accounting treats these regenerable layers
as fixed for the current projection and never promotes them into the digest.
Numeric `layers_before` and `layers` reports account for instructions, memory,
digest, retrieval, exact conversation and tool schemas. Output and the safety
margin remain separately reserved; 32k is a ceiling, not a target to fill.

Ordering is not authorization. Current corrections beat older memory; actual
tool receipts beat assistant claims of success. Historical commands and summaries
cannot confirm or replay actions. Specialists still receive only a scoped task
and approved memory packet, not this whole assembled prompt.

The configured ceiling is clamped to the cached discovered model limit.
Counting does not trigger discovery/network work per call. Unknown models use
the configured role ceiling; their provider limit still needs verification.

| Setting | Default |
| --- | --- |
| `MAIN_CONTEXT_LENGTH` | 32768 |
| `SPECIALIST_CONTEXT_LENGTH` | 16384 |
| `OLLAMA_CONTEXT_LENGTH` | 32768; shared local transport ceiling |
| `CONTEXT_COMPACTION_ENABLED` | true |
| `CONTEXT_COMPACTION_TRIGGER_RATIO` | 0.80 |
| `CONTEXT_COMPACTION_TARGET_RATIO` | 0.55 |
| `CONTEXT_RECENT_TURNS` | 4 |
| `CONTEXT_SUMMARY_ENABLED` | true; local async main-agent compaction only |
| `CONTEXT_SUMMARY_TIMEOUT_SECONDS` | 20; extractive fallback on failure |

An explicit legacy `OLLAMA_CONTEXT_LENGTH=16384` remains an operator ceiling;
raise it to 32768 to allow the main agent's full window. Changing environment
settings requires restarting the API.

## Accounting and overflow

The total includes system/runtime instructions, personal context, activated
skills, tool schemas, messages and tool-call arguments. Output space is reserved,
including the reasoning mode's scaled allowance. A safety margin of at least
512 tokens (5% of the window) is withheld as well.

The estimator uses UTF-8 bytes divided by three plus framing/schema overhead.
It is an estimate, not the model tokenizer. For local Ollama models it is
calibrated once per model (`agent/llm/token_calibration.py`): Vellum sends its
own runtime documents and a JSON tool-schema sample to the model with a random
prefix (defeating the prompt cache), reads Ollama's real `prompt_eval_count`,
and stores real-per-estimated ratios for prose and for structured text, each
with a 10% safety margin, in `data/llm-routing/token-calibration.json`.
Estimates inside a projection then use the structured ratio for JSON-like text
(schemas, tool results, tool calls) and the prose ratio otherwise. A model that
has not been measured keeps the uncalibrated (conservative) estimate;
`CONTEXT_TOKEN_CALIBRATION=false` turns calibration off. Each image reserves
8192 tokens; multimodal calibration remains future work.

Compaction starts when estimated input plus reserved output and margin exceeds
80% of the window. It aims for 55% input occupancy, preferring recent turns
while staying below the trigger. Protected instructions and a single current
user request are never truncated. Within a single long task, closed older
read-only tool rounds may also be compacted, with the two latest rounds kept
exact. Specialist read rounds carry the same `vellum_read_only` provenance as
the main graph's verified reads. Mutation rounds and unknown/dynamic tool
operations stay exact. If the protected material still does not fit,
`fit_context` recovers before rejecting: it first compacts as hard as a manual
compaction, then gives back only the extra output reserve a reasoning mode
added (never below the standard answer budget), and the routing engine caps
generation at the reserve that fit (`recovery` and `output_reserved` in the
report). Only when neither works does the request fail before provider
submission with a request to narrow the material. Disabling compaction retains
this overflow guard.
Disabling it stops future compaction; it does not expand an already compacted
checkpoint back into full history. The original saved chat remains available.

### Tool-result evidence store

Tool results that leave the working prompt stay retrievable
(`agent/conversations/evidence.py`, `data/memory/evidence.db`):

- MCP projections keep the full original. A connector call saves the
  normalized result (up to 2 MB) and adds an `evidence_id` to its summary or
  structured projection. It is captured below the thread boundary, so the
  record starts unclaimed; unclaimed records expire after an hour.
- The graph's tool step (`keep_evidence` in `graph/tool_reuse.py`) claims
  those ids for the conversation, saves other results longer than 1,200
  characters (shorter ones survive whole in the compaction excerpt), and
  replaces any result over 16,000 characters with its first 12,000 characters,
  its size and its id.
- Compaction digest entries carry the `evidence_id` of removed tool results,
  and the digest lists the 12 most recent under `evidence`.
- `conversation_history(evidence_id=..., page=...)` pages through a stored
  result (6,000 characters per page); with `query` it returns matching
  passages with their offsets. Records are readable only from the conversation
  that owns them and are returned as untrusted tool evidence, the same
  disclosure path as the original result.
- Deleting a conversation deletes its evidence (`SessionsReader.delete`);
  evidence older than 90 days is removed, matching history retention.

Specialist read loops still bound oversized results to an excerpt without
storing them; specialists have no recall tool to read them back.

### Replay baseline

`scripts/context_replay.py` replays recorded threads (rebuilt uncompacted from
`data/memory/checkpoints.db` through a private copy; no model calls) through
the current prompt prefix, visible tool schemas and budget, and reports
compaction rate, overflow rate, window use and how much tool evidence leaves
the prompt. On 2026-11-19, 54 threads with at least 20 messages (1,487 model
calls) on `ollama/gemma4:12b` at a 32,768-token window gave:

| Configuration | Compacting calls | Overflowing calls | Median / p95 window use | Tool evidence removed |
|---|---|---|---|---|
| Standard output, before | 10.9% | 0% | 62% / 71% | 79% |
| Standard output, calibrated + recovery | 3.0% | 0% | 46% / 66% | 66% |
| 8,192-token reasoning reserve, before | 72.9% | 5.4% (19 threads) | 61% / 65% | 81% |
| 8,192-token reasoning reserve, calibrated + recovery | 11.2% | 0% | 45% / 52% | 79% |

The fixed prefix alone (instructions, personal memory, visible tool schemas)
was about 18,000 estimated tokens before calibration (about 11,400 calibrated;
real gemma4 instructions measured 8,737 tokens).

`--evidence` applies the tool step's evidence ids and per-result bound to the
replay (nothing is stored). With standard output, calibration and recovery,
removed tool evidence fell from 66% to 51% of tool-result tokens, and the share
that could not be recovered (removed, longer than a digest excerpt, and with no
evidence id) fell from 63% to 0%; compaction (2.9%) and window use (46% / 66%)
were unchanged. Historic threads predate connector capture, so this measures
the main-graph path only.

## Persistence and privacy

The main graph runs its context node before inference and after tools. Older user
turns leave the current checkpoint as whole assistant/tool exchanges. Closed
read-only rounds within a long current task may also leave as complete batches.
Parallel calls/results stay together. The latest user request stays exact,
including short follow-ups such as `yes` and `??`.

A bounded `context_digest` lives in the same LangGraph SQLite checkpoint. It
contains local extractive excerpts with original roles/message IDs, prioritizing
the initial request, relevance to the current question and recent exchanges.
It is explicitly incomplete, injected as untrusted human-role evidence, and
cannot become an instruction, confirmation, publication receipt, shared memory
packet or durable user preference. Attachment privacy envelopes are not
flattened into digest text. Runtime recall blocks are not promoted into user
assertions. Personal memory and pending actions retain their existing owners.

Canonical `/api/conversations` history remains intact. Old checkpoint versions
are not vacuumed/deleted. A graph rebuild resumes its persisted digest. Existing
conversation deletion removes checkpoint state, including the digest. No second
summary database or cross-thread digest cache is added.

Specialist projections are task-local at the routing seam. They do not inherit
the main digest or unrestricted conversation history. Original reasoning-loop
evidence stays in the existing task runner. Deterministic specialists allocate
no model context when they do not invoke a model.

## Frontend and verification

### Manual compaction and original-source recall

Send `/compact` in chat, or select **Compact context** from the composer slash
menu and send it. `/compact focus on the calendar work` prioritizes that focus.
The command queues behind the same thread's active turn, invokes the existing
context node without running an ordinary agent turn or tools, and saves the
digest/removals atomically in the same checkpoint. It normally retains the last
two exact user turns. An unfinished graph/tool turn is preserved and reported;
an empty or already-small conversation is a truthful no-op. Manual compaction
works even when automatic compaction is disabled. It does not change the saved
chat, personal memory or pending actions. Reopening uses the saved digest.

On an eligible local async compaction, the selected Ollama model writes a short
JSON task map from the bounded attributed excerpts. Every accepted item must
identify source IDs present in those excerpts. No tools or cloud fallback are
available to the summarizer. A 20-second deadline, malformed output, unknown
source IDs or insufficient remaining prompt space leaves the extractive digest
usable. An optional semantic map is also rejected if it would expand the original
prompt. Source IDs validate attribution, not semantic correctness: the summary
is still model-generated and cannot certify a completed action. Internal summary
tokens never become the visible assistant answer. Sync/specialist routing
projections remain extractive.

The directly visible read-only `conversation_history` tool retrieves original
messages through ConversationLifecycle, with conversation/message IDs, roles,
timestamps, message indices and explicit truncation/continuation offsets. It
defaults to the current thread; `scope=previous` is explicit. The graph can also
prefetch a small current-chat evidence layer after compaction or on a recall
question, and prior-chat evidence on an explicit prior-chat reference. Ordinary
private continuity does not invoke public web search. Retrieval is bounded lexical
selection, not an exhaustive semantic search guarantee. Time metadata is source
metadata; retrieval time is not the date a conversation occurred.

Temporary chats are excluded from other chats. Deleted or missing canonical
sources cannot be revived from orphaned FTS entries. Memory/history settings and
recording-reference preferences apply when the per-turn personalization runtime
is installed. Its absence does not disable the canonical memory/history gates.
The canonical Memory Orchestrator supplies
saved memories; its generated USER.md/MEMORY.md exports are not injected again.
MemoryAgent consumes its approved profile memory packet, so an existing SQLite
memory no longer depends on whether a vault card has been exported. Empty profile
packets do not resurrect stale cards. Durable memory creation remains a separate
approved write flow; `/compact` never promotes a preference.
MemoryAgent's built-in read policy includes canonical `global` user memories in
addition to user-profile/shared/its-own scopes; other specialists' private scopes
are not widened. A custom profile can still narrow that policy. Legacy standalone
card readers remain available only when no canonical packet is supplied.

### Verification surfaces

The graph emits the content-free `vellum_context_compacted` custom event. The
existing SSE adapter maps it to `agent.activity`, type `context_compacted`, with
the label `Keeping earlier conversation context`, completed status and numeric
budget metadata. The existing frontend trace handles it without inserting
implementation details into the assistant's answer.

Focused tests live in `backend/tests/test_context_budget.py` and the existing
routing, graph, profile and frontend stream suites. The opt-in
`scripts/verify-context-budget-frontend.py` uses an isolated local API, a muted
disposable browser, the served frontend and real `ollama/gemma4:12b`. Synthetic
history exercises compaction, date/city retention, graph rebuild, canonical
history preservation and an actual 16k XAgent draft-only model request. Unrelated
connector health discovery is stubbed; chat and model inference remain live.
Evidence and screenshots stay under `.scratch`.

Compaction is lossy. Facts missing from selected excerpts require original
history retrieval. A larger window can increase KV-cache memory and latency.
Sustained concurrency, arbitrary multilingual tokenization, multimodal fit and
retrieval quality require separate workload validation.
