# Music workspace

Open **Music** from Vellum's sidebar, or the local preview with **?view=music**.

## Layout and appearance

The supplied **HANDOFF.md** and **vellum-handoff (1).zip** are the visual reference: 232 px sidebar, service selector, Manrope typography, five-column album grid, playlist/album tables and a 96 px bottom player. Vellum’s original sidebar/rail remains visible. The inner Music sidebar starts with the shared Personalization-style VSelect dropdown for Spotify, Apple Music and Local files; its duplicate Vellum heading is removed. Its own Hide/Show controls collapse and restore the 232 px panel independently of Vellum’s outer navigation. The selected provider and playback survive the toggle. This is session presentation. Mobile has the same provider dropdown in its header. The desktop menu anchors left inside the sidebar to avoid clipping behind Vellum’s outer navigation; the mobile menu stays within its control width. The outer Music icon is constrained to 18 px. Narrow layouts use a 64 px mini-player and bottom tabs. The design's sample artists, covers, counts and connection claims are not production data.

The user's later background instruction takes precedence over the supplied standalone theme palettes. The selected Vellum backdrop remains underneath Music. A translucent readability surface and the host's light/dark background tone determine text, fields and panels; provider/theme selection changes accents rather than replacing the Vellum backdrop. The surface has enough opacity to maintain contrast even when an animated background has bright regions while its metadata reports a dark tone. The local Manrope variable font ships with its OFL notice.

Home, search, playlist/album/artist details, Sources, Settings, now-playing Queue/Lyrics, local first-run/library/matching and metadata-preservation views share this shell. Apple Music is visibly deferred: no Apple sign-in, subscription playback, fabricated library or transfer results are exposed. Crossfade, gapless and quality controls are displayed as unavailable where the existing owner has no implementation. Lyrics remain an explicit unavailable state; opening the tab retains the current cover.

## Playback ownership and actions

Spotify continues to use its existing connection and Web Playback SDK owner. A React portal presents its canonical snapshot; changing between chat and Music does not remount that player. Transport, seek, volume, mute, shuffle, repeat and selected-source playback keep **spotify.playback.control**. Volume and position labels display measured state. Covers prefer the canonical player's artwork when a track projection omits its own artwork.

The local presentation uses the existing **agent.music_library** owner and **VellumLocalMusicPlayback** singleton. Files, playlist information and transport use the existing **local_music.file**, **local_music.playlist** and **local_music.playback** App Actions. File selection grants only the chosen files/folder. Owned audio is copied; missing playlist songs remain explicit placeholders. Playlist metadata export contains no local paths or credentials. This layout does not expose the earlier experimental YouTube recording-download controls.

Sources uses **spotify.playlists.link** to retain up to 20 exact playlist references in the canonical connection bundle, with account/connection checks in SpotifyClient. It does not follow, rename or otherwise change remote Spotify playlists. Disconnect/replacement retains the existing connection cleanup behavior.

Playlist rename/description/add/remove controls keep **spotify.playlist.edit**, its account/snapshot-bound confirmation and verified receipts. Removing a saved playlist means unsaving it, not deleting its contents. Song removal retains the connector's documented all-occurrences behavior.

Ask Vellum is removed from the Music sidebar. Mode/provider/screen navigation and accent previews are session presentation, not credential or account changes.

## Dynamic Island

The existing persistent player host also subscribes to the canonical local audio
owner’s measured snapshot. It does not start another audio element or claim a
lease merely to display the Island. A metadata read runs when the observed local
entry changes; progress ticks do not refetch the library. Local playback takes
the Island while active, including when Spotify is disconnected; measured Spotify
playback takes it back when Spotify becomes active. Paused local playback remains
visible when Spotify is idle. The existing pause-before-start interlock is kept.

Island transport dispatches the existing **local_music.playback** action for local
music and **spotify.playback.control** for Spotify. Local seek/volume drafts remain
presentation; labels use observed position/duration/volume. The local panel omits
Spotify connection/device prompts, shows a Local Music service icon and opens
Music with Local selected. Its audio owner survives Music-page navigation.

## Playlist reads and public fallback

The existing browse/search adapters and typed **MusicCardPage** remain the read boundary. Playlist tracks preserve original positions, duplicate occurrences and unavailable slots. Album/playlist playback uses exact context URIs; selecting a row uses its original offset even after display sorting. Liked Songs uses returned saved tracks. Artist details use the artist-track read and bounded track URI playback.

When Spotify refuses a playlist's items with **access_denied** or **resource_unavailable**, the backend can read the exact public embed's song metadata. That bounded client sends no OAuth headers or cookies, rejects redirects, validates the returned playlist identity, and never returns preview/audio URLs. A ten-minute, 32-playlist memory cache avoids repeated public page downloads while paginating. Authentication and rate-limit errors are not converted into successful empty results.

Public pages are labeled **source=public_embed**, **completeness=unknown**, with an explanatory **note** in the response and a **visible songs** count. The explanatory paragraph is not rendered in the playlist UI. Their available occurrences paginate normally and target the original playlist context. Public metadata can be incomplete, stale, region-dependent or unavailable. If it cannot be read, the existing sandboxed Spotify embed and exact-context playback remain available; there is no fabricated native list.

API-backed pages retain **source=api**. These fields are additive to the v1 contract. New App Actions and the revised served Music handlers are included in the action-parity inventory. Shared files are projected onto current main without unrelated connector, notification or Responses settings changes.

## Artwork and pending controls

Missing Spotify track covers use the typed **GET /api/plugins/spotify/artwork** metadata read. The latest page of up to 50 missing track covers starts warming as soon as song rows arrive, with a 1,200 px lookahead for other rows. Exact track IDs pass through the existing plugins adapter; four IDs share a batch, with at most two browser batches and four upstream metadata reads concurrently. The backend accepts at most 20 IDs, rejects redirects, sends no Spotify credentials/cookies to the public oEmbed endpoint, limits responses to 64 KB and allows only HTTPS Spotify image hosts. Successful results are cached for an hour; unavailable artwork remains a bounded placeholder. This is a read-only presentation lookup, with no App Action or playback side effect. Song rows appear without waiting for artwork. The HTTP read waits at most 350 ms for ready metadata, then marks unfinished items **pending**. The adapter retries only unfinished IDs (bounded to 30 retries); one slow image lookup no longer delays the ready covers in its batch. Images warm in the browser cache before scrolling. Local libraries use numbered song rows and compact playlist selectors, so files without artwork have no blank cover boxes. Embedded covers appear when present; the view does not search online using local filenames or tags.

Recently played snapshots keep canonical artwork, artists and duration as soon as the player observes a song. Their thumbnails stay 36 px wide; the fixed player retains its cover in Settings and Sources. Pending transport commands keep their colour and opacity while remaining locked against overlapping clicks. Unavailable playback stays disabled. Sources sync and link submission retain their appearance while pending.

LocalMusicEntry adds a derived **artwork_url**. Embedded JPEG/PNG/WebP artwork is read with Mutagen, limited to 4 MB and served by the access-gated local artwork route. Derived artwork and negative-cache markers live under the canonical library’s artwork directory, separately from immutable audio assets. Existing files are inspected on their next library read; original audio bytes and exported playlist metadata are unchanged. Missing, unsupported or malformed artwork never prevents audio playback.

Successful file/folder imports select **Imported files** and return to the local library. Loopback Origin validation accepts the verified Vellum UI even when a browser classifies localhost-to-127.0.0.1 as cross-site; foreign origins, opaque cross-site requests and missing mutation headers remain blocked. Audio/export URLs retain the workspace loopback hostname so native media requests stay same-site.

## Responsiveness and limits

Home shows individual recent songs first, then saved playlists and up to ten saved albums, with library browsing controls for more. Selecting a playlist from Settings/Sources explicitly opens its song view. Playlist shortcuts retain their own list when browsing albums.

Connected mode does not poll the local library. The action catalog is shared by the Music/local presentation rather than fetched twice. Local reads run only while Local is active and visible, at 15-second intervals; imports refresh explicitly. Large local song lists initially render 100 entries with Show more songs. Search offers song and artist suggestions from both Home and Search after two characters and a 300 ms pause. Stale lookups are aborted; Arrow keys/Enter select a suggestion and Escape dismisses it. Selecting a suggestion searches or opens artist tracks without autoplay. Enter still submits a full search. One borderless input inside one search container avoids inherited double borders.

The **Paste a link** card imports Spotify/Apple song or playlist metadata using **local_music.playlist**. It never treats subscription audio as a direct media file. Spotify playlist metadata imports reuse the same bounded public fallback on denied/unavailable lists, retaining unknown completeness. Direct audio URL, podcast-feed and cloud-file playback are visibly deferred. JSON playlist manifests and supported local file imports work through the existing owner; arbitrary playlist export formats, automatic fuzzy matching, provider transfer, lyrics services and new Apple capabilities are not claimed by this visual replacement.

## Verification

See [Scoped publication notes](verification/music-dictation-pr-2026-10-29.md). Screenshots are earlier synthetic fixtures from the shared development checkout. No tests or builds were rerun for this isolated draft PR, at the user's request. Provider metadata reads do not prove audible playback, native desktop behavior or long-session acceptance.
