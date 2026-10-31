# Response workflow and startup repair - 2026-10-30

This record covers the local response trace, startup/scrolling, sidebars,
OpenRouter failure diagnosis, and removal of the Books-only local-model gate.
Changes remain in the existing dirty checkout; no commit, push, branch or PR
was created for this work. Tests and production builds were not run, as requested.

## Observed causes

- The recorded 153-second capability turn did not compact: its checkpoint has
  four messages, no digest and `compacted=false`. Runtime preparation took about
  19 seconds, context preparation about 43 seconds, first answer arrived around
  135 seconds and completion around 153 seconds. This separates model/context
  latency from UI presentation.
- Prompt assembly repeatedly enumerated the same plugin manifests. The baseline
  profiler recorded 3,401 manifest parses and about 11.06 seconds. The existing
  registry snapshot reduces those reads to 68. One comparable assembly measured
  1.357 seconds; a later contended cold measurement was 8.571 seconds. A second
  assembly in the same invocation reused the request-local prompt in 0.0003
  seconds. These are assembly measurements, not end-to-end response guarantees.
- Initial metadata used one shared Promise.all barrier. The model picker waited
  for unrelated discovery. Startup also fetched all conversation messages and
  explicitly restored the last chat.
- The full conversation-library endpoint measured 44.893 seconds with the local
  33,748,867-byte conversation file. Read-only local profiling of the summary
  projection measured 0.278 seconds for canonical reads, 0.287 seconds for
  projection and 0.002 seconds for serialization across 253 conversations.
- OpenRouter authentication returned HTTP 200 with the configured key. No key or
  prompt was printed or sent to any other host. The local routing failures had
  no provider HTTP status. Privacy receipts recorded hard-blocked identifiers.
  Reconstructing the same context found one false government-ID detection:
  `account-scoped` in a tool result. After narrowing account-ID matching to a
  value containing digits, that same context had zero hard-block detections.
- Books synthesis used the same RoutedChatModel name as the main answer model.
  Filtering only by name allowed internal structured JSON into answer text.
  Sports independently treated a provider search JSON string as prose.
- Nested registry/underlying callbacks represented one delegation with two run
  IDs. The UI also displayed retrospective aliases after live events.

## Implementation

- Keep the existing SSE, response record, ToolRegistry, DelegationRuntime,
  AgentCatalog, provider routing and settings/action owners.
- Show one event-driven work trace. Filter runtime/context/compaction and argument
  preparation events. Expand live work, collapse completed work unless the
  reader chose otherwise, animate incoming icons/steps briefly, and respect
  reduced motion. No model/vendor name or logo is shown in the progress row.
- Show named delegations/tools and real returned sources. Emit public source
  progress immediately after a specialist read returns, before synthesis.
  Reading/read states require actual page extraction events/results, never just
  search discovery. Preserve distinct Book evidence anchors.
- Limit SerpAPI engine attempts to one shared 15-second search budget. Stop on
  provider error payloads. Explicit provider selection reports that provider's
  failure; automatic fallback skips the provider that already failed.
- Deliver structured stream failures and controlled provider/privacy messages.
  A post-header stream interruption is not an unreachable API. Partial answers
  remain available.
- Isolate answer tokens to the main graph answer nodes. Normalize structured
  Sports search results and recognize Book inventory wording without RAG
  synthesis. Recover presentation of the known older leaked envelopes without
  modifying saved history or treating their claim JSON as validated evidence.
- Memoize identical successful reads within one turn through the existing
  ToolNode. Never replay write/unknown/mixed batches or action/receipt results.
  Repeated reads transition to a bounded final answer. Automatic context
  compaction stays extractive; semantic local summarization is manual-only.
- Apply essential startup results independently; postpone nonessential discovery
  until model metadata is usable. Avoid reload-triggered memory dreaming.
  Summary library requests preserve derived organization while excluding
  transcripts. Normal conversation.open receipts hydrate full history; explicit
  deep links fetch only their selected record. Ordinary reloads stay home.
- Use the same follow hook in main and specialist chats: force new user turns
  into view, follow actual DOM/text growth, and respect reading earlier content.
- Main/Music/Plugins are inset off-canvas navigation. Desktop main-sidebar edge
  hover is transient; pin/unpin uses the existing canonical action. Explicit
  close suppresses hover until pointer departure. Reopen controls do not insert
  a header row or shift Share/options vertically.
- BooksAgent now permits the selected cloud model. Its Books-only local-model
  checks are removed. Normal disclosure/PII protection, selected-model pinning,
  Book claim validation, and confirmed discovery actions retain their owners.
- The unavailable Opus 5 Fast catalog entry is removed, with its legacy ID
  resolving to Opus 5. The other 21 curated cloud IDs appeared in OpenRouter's
  public catalog at inspection time; this does not prove endpoint eligibility.

## Verification actually performed

- Python AST parsed for 18 affected Python files; inline JSX and affected plain
  JavaScript parsed successfully. This is syntax validation, not test coverage.
- Scoped git diff --check completed successfully.
- The canonical runtime graph compiled without inference: about 1.252 seconds,
  including context, tools, final_answer and tool_failure nodes.
- Running API startup responses after the lightweight path: health HTTP 200 in
  0.032 seconds; models HTTP 200 in 0.531 seconds; library summaries HTTP 200 in
  0.511 seconds and 276,404 bytes. These are one local measurement, not a promise
  of identical cold-start or loaded-machine timings.
- Isolated browser replay used actual api/chat.js and response components with
  in-memory SSE. It showed Working without setup rows, named delegated work,
  real source links, completion collapse, no remaining animated orb after
  completion, and the explicit SerpAPI failure message. No legacy activity ledger
  was rendered.
- An isolated browser showed the landing page despite a saved previous-chat ID.
  Replayed DOM/stream growth with the actual shared hook confirmed that sending
  a new question jumps down, streamed content is followed, scrolling up is
  respected, and sending the following question resumes following. No page
  JavaScript errors were recorded in that pass.
- The effective BooksAgent profile reports source_egress=external and inherits
  model selection. OpenRouter key authentication and public catalog inspection
  succeeded; no cloud chat/completion or private Book-content request was made.

- Final actual navigation hydrated an existing summary into a chat with messages.
  The pinned sidebar closed while the pointer remained over the control, hover
  peeking reopened it, and pinning retained it after pointer departure. Share's
  viewport top was 17 px with the sidebar open and 17 px with it closed.
  Music and Plugins hide/reopen/backdrop controls completed on desktop/mobile.
  No page JavaScript errors were recorded. Mobile layout was then corrected to
  stack Plugin controls and use opaque navigation drawers rather than overlapping
  text through translucent panels. The confirmation capture measured a 390 px
  viewport with 390 px scroll width, main inset at (6,6), zero collapsed sidebar
  width, and no page errors.

Synthetic presentation captures (not live model/source retrieval):

- [Live work trace](response-workflow-2026-10-30/work-trace-desktop.png)
- [Returned/read sources](response-workflow-2026-10-30/work-sources-mobile.png)
- [Provider failure](response-workflow-2026-10-30/work-failure-mobile.png)

## Handler review and limits

The existing workspace-action runtime now serializes layout dispatch and builds
context after the prior receipt. This prevents mobile automatic collapse and
manual reopening from using the same base revision; rejection releases the
queue and does not disable later requests. A settled mobile follow-up confirmed
the plugin drawer is hidden at translateX(-280px) with no horizontal overflow.

Reviewed new controls: transient trace expansion/scroll state, main-sidebar hover
presentation, existing pin/reopen/backdrop actions, Music local navigation
backdrop, and Plugins canonical visibility backdrop. Reviewed response and Music
fingerprints were updated; streaming/accounts/progress fingerprints are
unchanged. Main-entry and Plugins fingerprints already differed from inventory
before these edits; their remaining drift was not blindly overwritten. The full
Action Parity suite, test suites, production build and packaged Electron flows
were not run. No claim of provider inference, all-model compatibility, live
source retrieval or end-to-end latency improvement is made from replay/syntax
checks alone.

Proposed PR title: Smooth response work traces, repair cloud routing, and speed up startup.

Proposed description: Replace internal setup/activity noise with a live named
work trace, isolate specialist structured output from answer text, preserve
provider failures and bound duplicate work. Load conversation summaries on
startup, follow new/streamed messages, and add aligned inset/off-canvas sidebars
with hover/pin behavior. Fix the account-scoped privacy false positive blocking
OpenRouter and let Book queries use the selected protected cloud route.
Verification is limited to the evidence above; tests/builds were intentionally
not run and provider inference remains unverified.
