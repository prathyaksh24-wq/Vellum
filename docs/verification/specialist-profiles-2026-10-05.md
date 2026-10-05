# Specialist profiles and memory handoffs

Date: 2026-10-05

## Delivered

Browser, Music, Sports, X, Books, YouTube, Discord, Calendar and Memory each
resolve through the existing AgentCatalog and DelegationRuntime. Every built-in
profile now contains its own instructions, Hermes skills, tool permissions,
private memory scope, model/reasoning configuration and response contract.

Each delegated run pins the selected model (or its profile override), loads its
approved context, and resets that context on exit. Inner routed planning and
synthesis calls inherit the same profile. Concurrent runs retain distinct
contexts. This creates separate application profiles; model weights and the
local model server can be shared.

Recognized actions retain the existing exact handlers, target resolution,
confirmation policies and receipts. Unfamiliar tasks can use a bounded reasoning
loop with permitted reads, skill inspection and memory requests. Models without
native tool support use validated structured steps. A model cannot insert
confirmation, rewrite an action target or invent its success receipt.

Memory Orchestrator resolves peer requests from `memory_from` or
`specialist_memory`. Packets contain purpose, source/recipient, user/thread,
references, confidence and expiry. Both profiles must permit sharing, and the
source must permit that export scope. Relevant saved memories and recent
source-backed results use the existing owners. Secret-bearing records, another
user's results and expired/unrelated results are excluded. Packet-dependent
answers are excluded from the global response cache. Packets do not grant write
authority or directly promote shared memory.

Calendar and Discord private data stays within those profiles by default;
approved shared-scope memories remain eligible. Spotify provider data stays in
the deterministic integration path, and automatic Music model context contains
only private music preferences. Books retains its evidence contract; generic
profile discussions are explicitly partial, without invented Book evidence.

## Verification

- Focused profile, delegation and system-prompt checks: 96 passed.
- Frontend suite on the combined working checkout: 248 passed across 34 files.
- Frontend production build: passed; existing classic-script Vite warnings remain.
- Full backend regression on the combined working checkout: 2,544 passed,
  five skipped. The harness disables the optional live Honcho client and uses
  fresh temporary stores. One existing Starlette deprecation warning remains.
- `git diff --check`: passed.
- Running API health: `ok=true`; all nine profile summaries report `hybrid`.

### Live local model checks

Actual Ollama `gemma4:12b` inference exercised the common profile reasoning loop
for all nine profiles using temporary SQLite memory, audit and routing stores.
Each run called `specialist_memory` for its own profile and correctly returned
its distinct fixture reference. All nine passed; two-inference runs took
10.72–14.72 seconds. A Books-to-X packet request also passed and attributed the
source correctly.

The test explicitly selected LLM execution to exercise that common loop. It did
not replace built-in hybrid action handlers in the running application. Fixture
memory was temporary and was not added to the user's profile. The Books generic
discussion produced a valid partial envelope rather than claiming grounded
Book evidence.

## Limits

These live checks establish local model/profile isolation and memory-tool
behavior. They did not retest connected-account reads or public writes, actual
playback, Honcho portraits, every specialist skill, frontend-generated model
responses, or physical browser interactions. Those provider integrations keep
their existing authorization and availability requirements. Application profile
isolation is not an OS or filesystem sandbox.

## Runtime integration

Changes were implemented in an isolated checkout and merged into the working
checkout with per-file three-way merges and concurrent-edit hash checks. Existing
browser, YouTube and music work was preserved. Original file backups are local,
ignored runtime artifacts. The API was restarted and its loaded profile catalog
was checked through `/api/agent-profiles`.

## Merge compatibility

Merged `origin/main` at `a77fd87305289c4a329c659a1b8f45fd9932db00`
into the specialist branch without rewriting history. Changelog conflicts kept
both the specialist-profile entries and the existing YouTube history/browser
entries. The existing runtime and new YouTube history changes merged cleanly.

Checks on this merged branch: 2,509 backend tests passed, six skipped;
248 frontend tests passed across 33 files; frontend production build passed;
focused merge checks passed (116 tests, one skipped); no unresolved conflict
entries or whitespace errors. The live Honcho client remains disabled in the
backend regression harness. Existing Vite classic-script and Starlette
deprecation warnings remain. This branch check is separate from the earlier
combined-working-checkout run recorded above.
