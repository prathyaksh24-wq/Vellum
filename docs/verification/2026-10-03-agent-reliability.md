# Agent reliability follow-up — 3 October 2026

## Reproduced failures

The previous day's saved chats showed an incorrect Rain Over Me artist, an original-track follow-up timing out, a new Liked Songs request reusing a failed song search, a personal YouTube data question returning public tutorials, and stopped Meditations synthesis. Six initial regressions failed against the previous implementation.

## Changes

- MusicAgent retains the song plan independently of playback-state questions. Original-version follow-ups reuse its title, use bounded catalog choices and require an artist when originality cannot be verified. Fresh collection requests take precedence over artist corrections. Missing context produces a clarification rather than a new model plan.
- Spotify uses a title field search and treats featured-artist credits as metadata. Remix/live/version qualifiers remain distinct. Liked Songs uses the saved-track library, and unavailable playback devices produce an actionable response.
- YoutubeAgent recognizes personal data/activity questions, preserves account-status routing, and queries the local Knowledge Core. Broad query words no longer become literal topic filters. Imported results are labeled as a snapshot.
- Agent Reach post/reply/quote operations require a numeric creation receipt and read the resulting post before success. Semantic CLI errors are rejected even with exit code zero. Missing receipts and failed verification are explicitly uncertain; writes are not automatically replayed. Other publication backends must provide a receipt.
- Book and music model calls request provider-neutral JSON object output. Ollama translates it to native JSON mode. The routing owner applies a total invocation deadline and releases credentials on cancellation. Book evidence labels are mapped exactly to canonical IDs; unknown evidence still fails validation. Book and YouTube profile versions invalidate earlier cached answers.

## Live checks

Used `ollama/gemma4:12b` through `/api/chat/stream`, the frontend's streaming transport, with persistence disabled for test chats.

- Personal YouTube data: returned imported history through YoutubeAgent without public search.
- Meditations: returned a validated, source-grounded answer in approximately 37–44 seconds after the source-label fix. No unsupported fallback was added.
- Music context: original-track corrections retained Rain Over Me and completed in about one second across a current-track question. Replying with Pitbull selected the collaboration and reached playback in about 1.6 seconds. Liked Songs reached Spotify's saved library. Spotify had no active device, so audible playback remains unverified.
- X: with explicit approval, published the named test post, read it back and checked its author and exact text, then deleted it through the agent's confirmation path.

Browser automation could not initialize because the Windows sandbox helper failed. These checks establish live API behavior; visual frontend behavior is not claimed. Credentials, private imported records and test-session files are excluded from this change.

## Automated checks

Focused tests cover the reported wording, featured artists versus remixes, uncertain X receipts, read-back failures, zero-exit semantic errors, JSON-mode translation, total deadlines and cancellation cleanup. The full backend suite is run with a short temporary directory outside the repository; a repository-local Windows temp path causes unrelated long-path storage and Git workspace fixture failures.

- Full backend suite: **2,334 passed, 2 skipped**. The local harness disables external Honcho SDK calls; this result does not establish live Honcho availability.
- Frontend suite: **221 passed**.
- Frontend production build: **passed**.
- `git diff --check`: **passed**.
