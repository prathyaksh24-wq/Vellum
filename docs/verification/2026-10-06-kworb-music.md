# Kworb MusicAgent integration — 2026-10-06

MusicAgent now reads public music statistics through `music_kworb` in the existing shared capability registry. The built-in MusicAgent profile includes the tool and advances its version. Typed delegation, Spotify tools, pending actions and memory ownership remain with their existing owners.

## Behavior

- Monthly listeners and artist rankings come from Kworb's listener table, with exact or conservative artist identity matching and retrieval dates. Successful reads bypass the main agent's web search and model generation; failed monthly-listener evidence retains that existing fallback.
- Artist songs and albums expose Kworb's stream rankings. These are incomplete statistics, not a complete discography.
- Daily/weekly country charts use the site's observed country index and exact track links. Replies retain the source chart date. Historical chart requests ask for clarification rather than claiming a current snapshot covers the requested past date.
- Album discovery uses the identified Spotify artist and the existing paginated album adapter, filters other artists and future releases, and orders verified release dates. It does not infer newest releases from Kworb's stream totals or compilation titles.
- Explicit chart playback sends the chart's exact track URIs to the existing Spotify playback capability. Listing charts or a model-generated listing cannot authorize playback.
- Fixed HTTPS source paths, typed inputs, bounded response sizes/timeouts and a six-hour/16-page process cache contain public reads. Cached replies retain their original retrieval timestamps. Failed refreshes do not return expired counts as current. No account credentials, listening history or conversation transcript goes to Kworb.
- Activity reports `music_kworb` rather than labeling these direct reads as `web_search`. Recognized statistics requests still seek public evidence when prior conversation context is attached.

## Automated validation

The regression suite covering Kworb, MusicAgent, collection matching, playback consistency, agent profiles, API routes and Spotify tools passed **290 tests** in 93.54 seconds. The final focused suite after activity-label/context fixes and schema-plan dispatch passed **19 tests**, including both normal and streaming API routes. Both runs reported only the existing Starlette/AnyIO deprecation warning.

Fixtures verify parsed numeric counts and artist IDs, country/period/date resolution, exact chart track identities, unsupported requests, expired-cache failure, tool permissions, read-versus-play authorization, album date verification, shared delegation and public-web fallback. Successful normal/streaming requests explicitly fail the test if they invoke the web-search provider or main model.

## Live validation

Read-only `/api/chat` probes used `store: false` and returned HTTP 200:

- David Guetta: **83,220,280** monthly listeners, rank **14**, retrieved 2026-10-06 from <https://kworb.net/spotify/listeners.html>.
- India daily top five: actual chart date **2026-10-04**, with source <https://kworb.net/spotify/country/in_daily.html>.
- Japan weekly chart: actual date **2026-10-01**, retaining Japanese titles, with source <https://kworb.net/spotify/country/jp_weekly.html>.
- David Guetta songs: stream-ranked entries from his Kworb artist page, dated **2026-10-05**.
- Drake latest/previous albums: returned released album names and dates from the connected Spotify artist catalog, with both Kworb identity and Spotify sources.

Initial reads took approximately 1–3 seconds. After the final backend reload, a cold listener request took 3.78 seconds and the cached request 0.81 seconds. `/api/chat/stream` returned India's dated top three in 2.16 seconds. All final probes reported exactly `music_agent` and `music_kworb` as their tools. The owned backend passed `/api/health` with HTTP 200 after reload.

These probes establish live public reads and connected Spotify catalog access. Chart playback was verified with exact-write fixtures; no new audible chart-playback test was performed. Kworb is an external HTML source whose layout and update schedule can change. Its dates and retrieval timestamps describe evidence freshness, not guaranteed real-time Spotify counts.
