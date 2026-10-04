# Music collection edits, mixed confirmations and album playback

## Reported failures and causes

The recent chat showed a failed dislike, a removal preview that stayed pending
when the user asked “what is happening in the nba and yes”, misspelled saved-song
lookups, and a latest Drake album request searched as a track.

- MusicAgent always proposed collection edits for a second confirmation.
- The dispatcher recognized confirmation only as the complete message; its
  independent-task splitter could not represent a confirmation clause.
- “Liked playlist” was parsed as a named playlist for edits. Named removals
  searched the public catalog with an exact title rather than the destination’s
  actual songs; command words and corrections leaked into the search title.
- MusicPlan had no album operation. The new artist-album read also exposed a
  live Spotify restriction: artist-album pages accept at most ten items, confirmed
  by both live requests and [Spotify’s API documentation](https://developer.spotify.com/documentation/web-api/reference/get-an-artists-albums).

## Implementation

- Clear song add/remove requests execute directly through MusicAgent. The
  adapter captures the exact track URI and collection, checks membership, writes
  once, and reads back membership. Failed or uncertain changes remain errors;
  they do not become success messages or automatic retries.
- Saved-song removals paginate the actual destination and use normalized title
  comparisons and conservative similarity ranking. Multiple versions need a
  target selection, which retains the removal operation and destination. Explicit
  artist names, correction prefixes, and current-song aliases are recognized.
- Public catalog lookup makes at most one broad query after an exact-title miss.
  Strong typo matching requires an explicit artist; ambiguous catalog versions
  continue to ask for a selection. The planner cannot invent resolved track IDs.
- One explicit confirmation clause can join independent specialist reads through
  the existing typed delegation runtime. Authority is still claimed from the
  existing pending-action store. Queued changes require their own authorization,
  and completed contributions stream immediately. Current-song edits also run
  alongside unrelated specialist questions without waiting for their answers.
- New direct song edits retire superseded music previews while preserving
  unrelated queued proposals. Playlist creation, public X writes, Calendar
  actions and raw capability permissions retain their existing approval paths.
- Typed album playback resolves the artist, paginates album releases, excludes
  singles and future releases, compares release dates, starts one album context,
  and verifies the currently-playing context. Missing, ambiguous or incomplete
  catalog evidence does not start an arbitrary release.
- Spotify skill guidance and the compact main-system instructions match these
  behaviors; the prompt remains within its tested size budget.
- Full-suite verification exposed two existing Windows timestamp ties. Curator
  backups now reserve unique ordered folders, and Knowledge Core job listing
  uses insertion order to break equal creation timestamps. Both have frozen-clock
  regression checks; storage owners and schemas remain unchanged.

## Verification

- The original music regressions went red before implementation. Final focused
  coverage includes 31 new music/search/routing cases, plus the affected existing
  music, delegation, prompt, API, plugin and curator checks.
- Full backend suite: **2,447 passed, 4 skipped**. External Honcho SDK calls were
  disabled in the local harness, as in the prior report.
- Frontend: **234 tests passed across 31 files**; Vite production build passed
  with its existing classic-script warnings. `git diff --check` passed.
- Live requests selected **ollama/gemma4:12b** on the frontend streaming API with
  chat persistence disabled. Recognized music intents deliberately use direct
  typed plans instead of spending model inference time on catalog decisions.

| Live request | Result | Time |
| --- | --- | --- |
| Add Until I Found You by Stephen Sanchez to the private QA playlist | One write; membership verified, no confirmation | 3.08 s |
| Remove “untile i found u” from that playlist | Correct saved URI removed; membership verified | 2.33 s |
| Play the latest Drake album | HABIBTI (FOMO), dated 2026-10-02 in the live catalog; album context verified | 3.41 s |
| NBA question plus yes to an exact legacy QA removal | Music result at 1.22 s; independent SportsAgent result later | 6.12 s total |
| Remove the misspelled title without repeating the playlist destination | Prior destination retained; membership verified | 2.34 s |
| Add it to my liked playlist | Current song added; membership verified | 1.64 s |
| Remove it from my liked playlist | Current song removed; membership verified | 1.64 s |

Streamed text matched the final response for these requests. The private QA
playlist’s original two URIs and order were restored, and the current song’s
original Liked Songs membership was restored. Playback was paused after the
album check and confirmed inactive. No public X action was performed.

## Limits

- Browser automation initialization failed twice with the Windows sandbox helper
  error. The live checks exercised the frontend’s HTTP/SSE path, not browser
  clicking or visual rendering; no visual frontend pass is claimed.
- Live Honcho health and model-generated sports fact accuracy are outside these
  checks. The mixed NBA request verified routing, separate completion and stream
  alignment; it does not certify every claim in the sports summary.
- Artist albums and named saved-song searches have page limits and deadline
  checks between provider calls. Large, incomplete or unavailable collections
  fail visibly instead of guessing. Ambiguous song versions still require a
  choice; that is target resolution rather than an extra write confirmation.
- Runtime logs, QA transcripts, credentials and local skill state are excluded
  from the commit. Unrelated research and existing working-tree changes remain
  outside this PR.
