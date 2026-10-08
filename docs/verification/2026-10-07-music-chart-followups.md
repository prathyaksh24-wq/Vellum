# Music chart and metadata follow-ups — 2026-10-07

## Reproduction and diagnosis

Read the affected saved Vellum conversation through its canonical local UI store. The exact requests included `Show Japan’s weekly charts.`, `play from the global charts`, `play the latest post malone album`, `play a song from france`, `top 10 songs from france` followed by `play it`, and artist/album-name questions.

The minimized fixture repro returned country `Japan’s`, country `the global charts`, and a song-title search for `it`. The first focused regression run produced **13 failures and one pass**. Public country parsing included surrounding words; discovery results were not retained for follow-ups; current metadata recognized only some phrasing. Live Spotify search also returned two distinct artist IDs with the display name Post Malone, so the existing single-identity gate rejected an otherwise valid latest-album request.

## Fixes

- Normalize possessive/article/chart wording and recognize regional chart playback requests.
- Retain bounded source-backed chart and album discovery in the existing MusicAgent conversation context. `play it` uses the displayed chart's exact URIs without a new search or chart fetch. Album-name questions use the verified album result; a single discovered album can be selected with `play it`, with Spotify identity verification before writing.
- Keep these follow-ups with MusicAgent when another specialist is selected. Existing thread isolation and the 30-minute context expiry still apply.
- Read live device metadata for bare and expanded artist/album questions, including the reported wording and `whta` album-name typo. Attached historical artist claims cannot supersede these live reads.
- Corroborate identically named Spotify artists against Kworb's stable artist ID, retaining ambiguity when no identity is verified.
- Require playing-track read-back for chart acknowledgements. Unverified writes do not report success and are not repeated automatically. A failed chart request retains its exact target for an explicit later play retry.
- Preserve discovery source links without falsely labeling a retained result as a new web-search request.

No parallel store, runtime, registry or API was added. No frontend implementation changed.

## Automated validation

The affected regression suite for MusicAgent, Kworb, collection lookup, playback consistency, profiles, API and Spotify tools passed **306 tests** in 107.14 seconds. Subsequent chart acknowledgement and explicit-retry checks passed **28 tests**. The final focused set including both normal and streaming API routes passed **33 tests** in 14.71 seconds. The broader/API runs reported only the existing Starlette/AnyIO deprecation warning.

The API checks attach an old claim naming Travis Scott, retain an unrelated selected specialist, list France's chart, submit `play it`, and ask for artist/album metadata. They assert exact chart playback, measured metadata, no main-model rewrite and preservation of the user's selected specialist.

## Live checks and servers

- The backend and frontend were started with the existing launchers; `/api/health` and the served Vellum page both returned HTTP 200. The final code was loaded after an owned-process API restart.
- Actual normal-chat reads resolved Japan's weekly chart and France/global daily charts with their observed source dates. `find post malone latest album` followed by `whta is the name of the album?` retained the same verified album.
- A direct read-only check of the existing album resolver corroborated Post Malone's Spotify identity through Kworb and returned the released album August 26, dated 2026-08-26, using the paginated Spotify catalog.
- Initial playback probes returned no active device while the backend reported playback disabled. After the user reloaded the served Brave page and enabled playback, the backend reported the Vellum player ready and Spotify exposed its device. The existing heartbeat restored the session after the final API restart.
- The subsequent live player exposed BbY WOW with KAROL G, Judeline and rusowsky. The typed artist question returned those same credits through MusicAgent.

The user subsequently confirmed that chart/album playback worked, then reported the separate compound-action failures documented in `2026-10-07-music-compound-actions.md`. The automated checks establish exact writes, playback read-back, follow-up routing and failure behavior. They do not establish sustained playback over days/months.
