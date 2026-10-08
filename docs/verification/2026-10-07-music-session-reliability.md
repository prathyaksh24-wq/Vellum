# Music session reliability — 2026-10-07

## Reproduction

The existing local conversation `17h4sifz` contained these failures:

- `play a random song from any of my saved playlist` searched for a named playlist instead of selecting from the saved collection.
- `how many playlist i have saved?` claimed zero with no tools, although a live saved-playlist read returned 19.
- `Play One Right Now, then set volume to 25% and turn on shuffle.` chose David Shannon/Frank Rivers. Spotify's original catalog title includes `(with The Weeknd)`, which the exact-title comparison rejected.
- `no from post malone` reached the general model and timed out after the compound request ended with a player control.
- `play her loss album` played a track titled `Her loss album` by TrapNime. The next user message was `no the album by drake and metro boomin`.

Exact regression cases failed before implementation. Read-only Spotify catalog/account checks established the saved collection, the credited title suffix and the album identities. Her Loss has multiple unrelated exact-title albums; the Drake release is credited to Drake and 21 Savage. Blindly selecting the first result is unsafe.

## Changes and boundaries

The existing MusicPlan, MusicAgent, Spotify integration, normal/streaming chat dispatch and canonical specialist thread context remain the owners. No second runtime, store, provider router or endpoint was introduced.

Saved collection requests use a provider-neutral `play_saved_playlist` operation. Only returned saved identities are candidates; known empty playlists are excluded. Named playlists keep exact saved-library matching. Count/retrieval wording routes to fresh reads despite attached old chat context, and an API error cannot become a zero count. Pagination completeness remains required.

Song matching removes a trailing `with` label only when the label matches actual credited artists. Punctuation within artist names is supported; uncredited labels and remix/version labels remain distinct. Explicit artist requests remain authoritative. A bounded title-only fallback allows spelling corrections to be checked against real credits, without a song-to-artist lookup table or model-generated catalog identity.

Recent song/album references survive ancillary controls and active music queries in the existing state store. Changing the selected collection or skipping clears stale recording references. Missing/expired corrections ask for the title immediately rather than waiting on the model. The thirty-minute inactive context expiry remains; this change does not authorize old playback or unfinished actions indefinitely.

Title-before-`album` grammar retains full album playback intent. Real album choices expose actual artists and accept artist follow-ups. A recent older `... album` request incorrectly stored as a song is reparsed on use, without migrating user data. If an incorrect collaborator excludes all exact albums from the first search, one title-only retry finds catalog choices while still enforcing artist credits. Album commands never fall back to tracks.

## Verification

The affected suite passed 395 tests before the final live-search refinement. A subsequent live check reproduced an artist-filtered empty album response, which permissive catalog fixtures had not modeled. A new regression failed with the same generic no-match result before adding the bounded retry. The final complete affected suite passed **396 tests in 182.16 seconds**, with only the existing Starlette/AnyIO deprecation warning. Scoped `git diff --check` passed.

Coverage includes normal and streaming chat with attached old context, saved random selection, count/read failures, playlist typos, credited title suffixes, explicit artists, album ambiguity, wrong collaborators, legacy album recovery, compound continuation and a simulated eight-hour active session followed by state-store/dispatcher reload. Simulated time is not a real eight-hour audio soak or months of uptime. Existing playback, authentication/device lifecycle, charts and delegation tests are included. No new frontend change was needed.

## Live checks

On a separate test thread with conversation memory storage disabled, the running backend returned:

| Request | Result | Seconds |
| --- | --- | --- |
| `how many playlist i have saved?` | 19 saved playlists | 3.56 |
| `retrieve my playlists` | Actual saved names | 1.60 |
| `play a random song from any of my saved playlist` | 2000s bangers with shuffle | 3.22 |
| `Play One Right Now, then set volume to 25% and turn on shuffle.` | Post Malone/The Weeknd; volume 25%; shuffle on | 4.23 |
| `no from psot malone` | Correct original recording | 2.68 |
| `play the Her Loss album by Drake` | Full album, Drake and 21 Savage | 2.52 |

The subsequent player read showed Rich Flex by Drake and 21 Savage, playing true, measured volume 25%, SDK ready. These calls changed playback/settings only; no library or playlist mutation was made. Read-back does not establish physical speaker output.

After the final legacy-context fix, the owned backend was restarted with repository command-line and recorded parent/listener ownership checked before stopping. Health returned HTTP 200. The original chat's several-hour-old target had expired and returned an immediate title clarification in 1.27 seconds, with MusicAgent tool routing and no model timeout. Reissuing the explicit album title in that same chat returned actual album artists in 1.62 seconds. The wrong collaborator correction then exposed the empty filtered search in 1.34 seconds. `by Drake` correctly attempted album playback but reported no active Spotify device in 3.09 seconds; the browser lease was disabled. It did not claim playback succeeded. The retry fix and final device check are recorded below.

The final backend started at 15:41:28 Asia/Calcutta after the last code change. `play Her Loss album by Drake and Metro Boomin` then returned actual album choices including Drake and 21 Savage in **2.78 seconds**. `how many playlist i have saved?` returned the same **19 actual saved playlists in 1.81 seconds**. Both used MusicAgent, with no library mutation. Frontend and backend health returned HTTP 200. The user chose to test playback in Brave; final post-restart audible playback remains user verification rather than a claimed automated result.

All task-specific pytest scratch directories were removed after completion. Unrelated browser/YouTube scratch work and existing working-tree changes were preserved.

Account visibility remains limited to what Spotify returns: unavailable personalized mixes require their Spotify link. This work does not prove long-term provider uptime, protected-audio support in every runtime or automatic radio beyond a finite queue.
