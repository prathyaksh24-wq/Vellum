# Spotify controls, automatic player activation, and X publication

## Scope and ownership

Extend MusicAgent, its typed MusicPlan/proposals, the existing Spotify capability service and connector, the existing browser playback controller, and Agent Reach X provider. Confirmation continues through the canonical pending-action store and App Actions. No new runtime, database, provider router, or API surface is introduced.

## Confirmed causes and changes

- Backward seeking, relative volume, and repeat phrases could miss direct MusicAgent routing and fall through to slow model planning. They now use typed plans, including common seek wording and the reported `sens` typo.
- Spotify accepts a control before its state endpoint necessarily reflects it. Seek verification now accepts the bounded post-seek trajectory while rejecting an unchanged trajectory; volume/repeat/shuffle use bounded read-back checks. Each control mutation is issued once. Failed verification retains the requested volume amount for a contextual follow-up.
- `add it to my liked songs` could mean play Liked Songs. Save/remove/membership intents precede playback interpretation. Proposals capture the exact song URI and playlist, so changing songs before confirmation cannot change the approved target. Membership reads paginate and disclose incomplete all-playlist coverage.
- Spotify's public source-playlist contents returned 403. Curated creation now previews actual catalog results when that read is forbidden, preserving the requested name/count and explaining that these are not verified trend rankings. This follows Spotify's [February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide).
- Play requests activate the existing browser player from the Send gesture and await device registration before chat submission. This covers main and specialist chats and mixed media requests. An absent controller is awaited rather than silently selecting another device. A ready player in another window is reused only when Spotify lists that device; a confirmed disconnected device can be reclaimed after its registration grace period. Browser audio-policy failures stay visible.
- Explicit stop releases an owned local player only after Spotify reports that same device paused. Pause keeps it ready to resume. `play a song` selects real Liked Songs rather than searching for the literal title `a song`.
- X shorthand/corrections request a draft rather than search. Exact post text and explicit X links route directly; after confirmation, the active specialist is retained for contextual follow-ups unless the user selected another agent.
- Agent Reach post/reply/quote shares a 25-second write/read-back budget including CLI lock waits. Drafting is bounded to 20 seconds. An uncertain write is reported without automatic republication.
- Full-suite checks exposed credential ordering flakiness when creation timestamps tie on Windows. The canonical credential store now preserves insertion order on ties rather than random UUID order, with a regression test.

## Automated verification

- Backend: **2,396 passed, 2 skipped**. The ignored local harness disables external Honcho SDK calls and uses a short fresh temporary directory.
- Frontend: **231 passed across 30 files**, including immediate audio activation, device readiness before submission, initial component registration, mixed requests, shared/disconnected owners, connection deadlines, and verified stop.
- Production Vite build passed. Existing classic-script bundling warnings remain; the existing build plugin copies the API/component assets.
- Focused playback and routing checks passed, including unchanged-state rejection, delayed application, 20 repeated controls without model planning, exact captured collection targets, paginated membership, X timeout/no-replay, and credential timestamp ties.
- `git diff --check` passed.

## Live verification

Requests used `ollama/gemma4:12b` through the frontend's `/api/chat/stream` protocol with chat persistence disabled. Streamed text matched final text.

| Check | Outcome |
| --- | --- |
| Approved X public post | Published the exact approved reliability test text, read it back, then deleted that exact post and verified absence. Publication receipt arrived in 22.06 seconds. |
| Exact X preview after routing fix | 0.59 seconds; no second publication. |
| Approved private playlist | Created `Vellum QA Current Picks 2026` with the two approved catalog songs and verified name/song read-back. Preview: 2.08 seconds; creation/verification: 1.83 seconds. Playlist remains in the account as approved. |
| Automatic Vellum playback | User confirmed it worked after refreshing and retrying. Independent Spotify state reported Vellum as the active device. |
| Final repeated seek pass | 12 forward/back commands verified, including 10- and 15-second moves. |
| Repeat | On/off verified against actual playback state. |
| Relative volume and follow-up | 99% to 69%, then `increase by the same amount` restored 99%; both changes verified. |
| Final control timing | All 16 controls verified; 1.39–3.20 seconds, mean 2.09 seconds. |
| Current-song membership | Liked Songs read succeeded. All-playlist lookup checked 11 readable playlists and disclosed inaccessible playlists; it did not claim global absence. |

The initial live pass exposed lagging state reads and a failed-control context gap. Those were corrected before the successful final pass. Test seeking and volume changes were audible to the user; the final pass restored the initial volume and repeat setting. No control tests continue in the background.

## Limits and release notes

- Browser automation could not initialize because the Windows sandbox helper failed. No automated visual or independent audio-quality pass is claimed. Automatic activation has user confirmation plus independent API state evidence; automatic stop has deterministic frontend coverage.
- Current-song add/remove uses exact-target confirmation and verified read-back, with deterministic regression coverage. Additional live library edits were not made without concrete authorization.
- An all-playlist query is bounded and may report incomplete coverage when Spotify restricts a playlist. A named playlist can be checked separately.
- Local checks do not establish live Honcho health. Credentials, imported personal records, runtime state, and test chat transcripts are excluded from Git.
- PR #202 was merged into the follow-up branch after that branch's earlier merge to main. Main does not yet contain its commit; this PR also carries those already-reviewed parallel streaming and personal media changes into main.
