# Combined music actions — 2026-10-07

## Reproduction

Read the user's latest local Vellum conversation through its existing UI conversation store. After listing Spain's top 20 songs, the exact failed requests were:

- `play it and like this song that is playing` became a song-title search for the entire sentence.
- `like this song and play the spain sogns` fell through to the previously selected specialist and returned a false inability to perform music actions.

Both failures reproduced before implementation in the shared dispatcher fixture. Additional regression checks reproduced a stale pending library edit and saving the previous song when a requested new song had not yet appeared in playback state.

## Changes and ownership

The existing MusicAgent now separates bounded music actions using the shared App Action clause parser with an optional action-start filter. The filter preserves quoted titles and artist punctuation; existing parser callers retain their default behavior. MusicAgent executes its existing validated single-action plans in order within the canonical delegation/profile permission scope. No additional runtime, store, registry, endpoint or frontend state path was created.

Current-song library targets joined with `and` are captured through the permissioned live player before any action changes playback. A `then` boundary resolves subsequent current-song references after verified playback. Combined song, playlist, podcast, resume, pause and track-navigation controls require read-back before dependent steps continue. A delayed or unchanged old-track observation stops the request; it cannot silently save the wrong song or repeat the playback write.

Each action retains its own receipt, activity and source records. Invalid typed arguments are rejected before writes. The first failure, unresolved choice or confirmation preview stops subsequent steps and identifies them as not run. Playlist creation and recommendation acceptance keep the existing pending-action owner and confirmation. A new explicit compound library edit supersedes an older pending library-edit target.

Chart/album discovery uses the existing specialist context with an attributed plan and original expiry. Library edits and player controls retain the displayed chart without extending its 30-minute lifetime. `play the Spain songs` and `sogns` resolve that same captured chart. Older contexts remain compatible. Both normal and streaming API routes recognize compound actions as live requests even with stale attached conversation text and an unrelated selected specialist.

## Validation

The initial two saved-chat reproductions failed before implementation. A broader affected run passed 300 tests before the final transition check. The transition check then reproduced an incorrect old-song save; after adding playback read-back, the focused compound/API set passed 22 tests, including all exact user requests, ordered controls, target binding, stale-pending removal, confirmation, failure, invalid arguments, expiry, quoted titles and artist punctuation.

The complete affected set (MusicAgent, collection search, playback consistency, Kworb, normal/streaming API, delegation runtime and App Action settings) passed **302 tests** in 122.37 seconds. A final regression caught the public-statistics fallback discarding an already completed compound control. The dispatcher now preserves those receipts rather than passing the entire request back to the main model. After that adjustment, **45 MusicAgent/Kworb checks** and **11 API checks** passed. Existing single monthly-listener failures still retain their public-web fallback.

One collection attempt encountered a temporary mismatch between the concurrently changing YouTube contribution and its manifest permissions. A fresh standalone API import and the subsequent complete run succeeded once the manifest was consistent. The completed API runs reported only the existing Starlette/AnyIO deprecation warning. Scoped `git diff --check` passed.

## Running server and live read

Loaded the changes with the existing backend launchers after checking the recorded process, repository command line and the owned listener. Backend `/api/health` and the served frontend page returned HTTP 200; the Vellum device reported ready after its existing heartbeat restored the lease.

Submitted the exact combined typed request `what is playing and who is the artist` through `/api/chat`, on a separate test thread with conversation storage disabled. Both receipts returned BbY WOW with KAROL G, Judeline and rusowsky, matching the live player. The first receipt correctly reported paused playback. The response used MusicAgent and did not change playback, volume or library membership.

Fixtures verify exact library/playback write requests, membership read-back, ordered controls and delayed-state failures. The user's previous chart/album listening check succeeded; audible combined playback and real library edits remain their next check. A read-only smoke test does not establish audible output or months of uptime.
