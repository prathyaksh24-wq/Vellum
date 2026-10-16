# Ordered context management, manual compaction and source recall

## Scope

Extend the existing 32k main / 16k specialist budget work with a fixed assembly
order, source-backed older-context recall, separate durable personal memory,
optional local semantic task summaries, and `/compact`. Verification below was
performed in the original shared checkout before publication. Unrelated browser,
YouTube, voice and provider changes were preserved.

For the draft PR, the context changes were projected onto current `origin/main`
in an isolated worktree. No tests or live checks were rerun for that projection,
as requested. Changelog/test overlaps were resolved textually. The unmerged
per-turn personalization runtime is an optional integration: when installed,
recall uses its existing policy; otherwise canonical memory/history settings
still apply. Unrelated settings tools and voice/account changes are excluded.

## Implementation

- `agent/llm/context.py` still owns accounting/projection. It understands the
  personal-memory and retrieved-history layers, reports their before/after costs,
  supports a focused forced projection, and optionally validates a bounded local
  summary with source IDs. Unknown IDs, bad output, timeout or insufficient budget
  falls back to excerpts. A summary is evidence, not proof or authorization.
- `graph/agent.py` assembles instructions, personal evidence, digest, retrieved
  originals and recent exact conversation in that order. Regenerable evidence
  never becomes a user-authored checkpoint turn or a new durable memory.
- `LazyAgent.acompact` uses the same context node and checkpoint writer; the chat
  command queues behind the thread's active turn, refuses unfinished graph work,
  and runs no ordinary agent/tool turn. The original saved chat is retained.
- The existing composer slash menu offers **Compact context**. Chat accepts
  `/compact` and `/compact focus on ...`; existing SSE activity and completion
  events report observed outcomes. Internal summary inference is not streamed as
  the assistant answer.
- `conversations/recall.py` and the read-only `conversation_history` tool read
  canonical sources through ConversationLifecycle. IDs, roles, original time
  metadata, explicit truncation and continuation offsets survive. Current-chat
  recovery is allowed independently of global memory; cross-chat history honors
  memory/history settings and excludes temporary chats. Deleted sources cannot
  be revived by dangling FTS rows. Dated queries use source timestamps in the
  user's timezone when available.
- Memory Orchestrator remains the durable owner. Main prompt packets omit the
  extra FTS injection and duplicate generated snapshot files. Disabled memory
  omits cached portraits. MemoryAgent consumes its approved canonical packet;
  its default read policy now includes `global` user memories, with a profile
  version bump. Other agents' private scopes are unchanged. Legacy standalone
  card access remains when no canonical packet was supplied.
- Fork restoration checks an existing checkpoint before parsing the saved-chat
  archive. This removed unnecessary archive reads on established conversations
  and restored the existing stream/model-switch coordination checks.

## Live frontend verification

Command: `python scripts/verify-context-budget-frontend.py --main-only --management`

Used the served Vite UI, a disposable headless muted Edge browser, an isolated
local API/checkpoint/memory/vault, synthetic chat history and **real local
`ollama/gemma4:12b`**. Only unrelated plugin-health discovery was stubbed.
The helper pins imports to this checkout, avoiding an editable-package pointer
to another worktree. It did not publish posts or change live provider accounts.

Passing evidence: `.scratch/context-budget-live-87724f9d68/evidence.json`.
Screenshot inspected: [manual compaction and recall](context-management-2026-10-16/manual-compaction-recall.png).
It contains synthetic QA conversation content, including a synthetic passphrase.

| Check | Observed result |
| --- | --- |
| Automatic compaction | Estimated input 40,045 -> 17,139 tokens; local summary succeeded |
| Correct old date/city | Invitation retained 23 November 2026 and Kochi |
| Reopen/rebuild checkpoint | Follow-up invitation retained the same date/city |
| Slash menu | Selecting Compact context inserted `/compact` into the composer |
| Focused manual command | Estimated input 20,574 -> 16,320; 4.71 seconds; `local_hybrid` checkpoint persisted |
| Original older message after compaction/reopen | Correctly recovered synthetic passphrase CEDAR-482 from original message u3 |
| Durable personal memory | Returned “You prefer terse writing with no emojis.” from the approved canonical memory packet, without a generated vault card |
| Previous chat | Correctly referenced the earlier recycled-paper badge discussion |
| Saved chat and frontend | Canonical history retained; no page JavaScript errors |

The older-message answer used the automatic original-source evidence layer; it
did not emit a `conversation_history` tool call. Tool paging and policy behavior
were checked separately in backend tests. Memory recall and the simple previous-
chat answer used deterministic canonical paths; the invitations and continuation
used real Gemma inference. This is not proof that every paraphrase or old topic
will be retrieved.

Initial live runs exposed MemoryAgent's export-only lookup and missing global
read scope. Both were fixed before the passing run. A separate invocation first
resolved Python to another worktree; explicit canonical import anchoring fixed
that test-harness issue. Failed runs are retained separately under `.scratch`.

## Automated verification

- Full frontend suite: **431 passed in 44 files**.
- Production Vite build: **passed**; existing classic-script bundling warnings remain.
- Focused context/memory/profile/privacy backend run: **263 passed** before the
  final checkpoint-restoration regression was added.
- Checkpoint-restoration and coordination follow-up: **15 passed**, including
  the two existing one-second coordination checks without timeout changes.
- Final context/prompt checks: **59 passed**, including specialist-view command
  annotation parsing and a regression proving an optional semantic map cannot
  expand the original prompt. These overlap the core run.
- Combined affected backend run: 386 passed and two repair-test interface stubs
  failed after checkpoint inspection was moved earlier. The stubs now accept the
  runtime's model-scoped read arguments and simulate tool failure by actual state
  instead of the number of reads. The complete affected API/stream/privacy/tool
  suites then passed **124 tests**. Core checks and coordination follow-ups are
  listed above; these counts overlap and are not additive.
- `git diff --check`: passed; existing LF/CRLF warnings only.
- Backend reloaded with the completed implementation; `/api/health` returned
  `ok=true`, and the served frontend returned HTTP 200.

A broader run including `test_live_qa_regressions.py` also found an unrelated
YouTube discovery fixture failure (`test_discovery_response_uses_bounded_local_interest_evidence`):
its partial service fixture does not provide the browser-history method now used
by the separately modified YouTube path. YouTube implementation was not changed
for this task. The entire repository backend suite was not run.

## Limits

This adapts useful continuity patterns; it does not implement OpenAI's encrypted
provider compaction protocol. Summarization and lexical retrieval remain lossy.
Validated source IDs do not prove a model summary is semantically correct; exact
details still require original sources. The 20-second summary deadline bounds
that extra pass, not the whole answer. No sustained concurrency, arbitrary
multilingual retrieval, huge-archive scaling benchmark, cloud compaction, or
multimodal OCR behavior was verified. Old checkpoint versions are not vacuumed.
The live personal-memory check exercised SQLite and its scoped profile packet;
it did not establish live Honcho/dialectic or embedding-service readiness.
No new persistent memory store or automatic preference-promotion path was added.
