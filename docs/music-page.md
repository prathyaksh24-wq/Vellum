# Music page

Open **Music** in the sidebar, or use the local preview URL with `?view=music`.

The page uses the existing Spotify connection and Web Playback SDK owner. It does not create a second player or a separate library store. A React portal presents the existing `SpotifyPlayer` snapshot on the Music page; changing between chat and Music keeps that controller mounted. The browser workspace retains its session while its presentation is hidden on Music.

## Available interactions

- Search Spotify songs, artists, albums and playlists. Search is an explicit catalog read; stale requests are cancelled/ignored. Choosing an album or playlist opens its track list. Choosing a song starts playback from that result through the existing App Action.
- Browse saved playlists and albums in grid or list view. Square artwork stays complete rather than filling a cropped landscape frame. Liked Songs appears as a collection item, without a separate tab, and reads saved tracks rather than searching for a playlist name.
- Open a collection to inspect its cover, song count, artists, albums and durations. Its Play button starts the collection; selecting a song in a playlist or album starts at its exact source position and retains the collection context. Track lists have paginated loading, disabled unavailable rows and error/retry states. Back restores the collection scroll position. Opening a collection does not start playback.
- **Sort** changes the displayed collection order by name, or a song list by title, artist, album or duration. It loads remaining pages before applying an order, preserves original source positions for playback, and can return to Spotify order. Refresh resets sorting before reading the first page. Sorting does not rewrite Spotify playlists; complete sorts are bounded to 5,000 loaded rows.
- Open a playlist and choose **Edit playlist** to rename it, edit its description, search for songs to add, or remove songs using the row controls. The backend exposes editability only for verified owned playlists. **Remove from library** unsaves a followed or owned playlist without deleting its contents. Edits display the exact proposed change, then use the existing App Action confirmation path to save or cancel. Track removal removes every occurrence of the chosen URI.
- Typed App Actions use the same playlist editor: `rename my Tamil playlist to Road Trip`, `change the name of this playlist to Evening`, `set the description of this playlist to Songs for the long way home`, and `remove this playlist from my library`. “This playlist” uses the playlist last opened on Music while navigating to chat; Back to your collection clears it. Named commands require one exact saved-library match. Confirmation binds the account, playlist ID, current name and snapshot, rechecks them before writing, and verifies the provider result. Complete editing commands keep their chat messages and avoid conversational model delays.
- Select an upcoming track; playback starts at the selected position in the returned upcoming list. Three rows are shown initially, and **See queue** reveals the remaining returned rows. The queue uses the canonical player's existing distinct upcoming projection.
- Play/pause, previous/next, seek, shuffle, repeat, mute and volume use `plugins.spotify.action`. Volume and playback labels display the measured snapshot rather than assuming a write succeeded.
- The current cover remains a normal image beside the title. A display-only 40-by-40 canvas produces the pixelated vinyl label from that same cover. It never reads back or exports image pixels. The record rotates smoothly while the canonical snapshot is playing, pauses at its current angle and resumes from that angle. Reduced-motion preferences disable rotation.
- Spotify is implemented. Apple Music and YouTube Music show explicit unconnected states until those integrations exist.

The compact chat player moves to the lower corner, becomes clearer on hover/focus, and is hidden while the browser panel is visible. It has an **Open Music** entry. On narrow layouts Music has a **Back to chat** control and keeps queue access available.

## Read contracts and ownership

The existing browse contract also accepts `playlist_details` with `source_id`, returning the verified playlist description, owner ID and editability. The Music page discovers `spotify.playlist.edit` through the App Action catalog; UI and typed changes share the same external-write permission, confirmation and receipt owner.

`GET /api/plugins/spotify/browse` accepts `playlists`, `albums`, `liked`, `artist_tracks`, `playlist_tracks` and `album_tracks`. The two collection-detail kinds require `source_id`. `GET /api/plugins/spotify/search` accepts a catalog query and `track`, `artist`, `album` or `playlist` kind. Both return the typed `MusicCardPage` projection containing only display/selection fields. Track pages include duration and exact source position, retain duplicate tracks and preserve unavailable slots so pagination cannot shift playback selection. Search preserves the Spotify catalog privacy gate. Authentication and upstream failures return errors; the UI does not present a failed read as zero saved playlists.

These endpoints call the existing portable Spotify tools/client. The existing typed playback request additionally accepts one exact `context_uri` or a bounded list of track/episode `uris`; optional `offset_position` requires a context and maps to Spotify's position offset. Conflicting sources and source arguments on non-play actions are rejected. Capability discovery advertises the read endpoints. Frontend reads go through `VellumApi.plugins`; mutations retain App Action authorization, deduplication and receipts.

## Current limits

The collection shows what Spotify returns to the saved-library API. Personalized mixes that Spotify does not expose there cannot be inferred from their names. Direct search returns Spotify's catalog ranking and can include public playlists; saved collection selection always uses the exact saved identity. Liked Songs starts a bounded batch of up to 50 tracks. Queue selection uses up to 50 returned entries, rather than pretending to expose Spotify's entire future autoplay plan.

This change does not install playback support in Codex's browser. Use Brave with protected-content support for the final audible check. Search/library reads do not require an active playback device. Controls that depend on measured volume remain disabled until a device snapshot is available.

## Verification

The Music page, Spotify playback and playlist actions have automated coverage for detail navigation, sorting, pagination, exact source positions, cancelled reads, account and revision changes, duplicate removal, cancellation and unverified provider responses. The production build includes the components, CSS and artwork assets.

Disposable browser fixtures were inspected at desktop and 390-pixel widths. Connected-account reads verified playlist metadata and editability; a rename review was prepared and cancelled without changing the playlist. Provider writes were tested with a disposable transport, rather than applying edits to the owner's library. These checks do not establish a multi-day audible playback soak test.

## Playback and linked collections

Transient backend heartbeat failures preserve healthy SDK audio and device identity. Real SDK disconnect or authorization events still reconnect, and ownership conflicts release this window's player. Transport commands release their guard after the mutation receipt; background queue reads do not hold the controls or fade them out. Resume sends no source URI or seek offset.

Playlist permission failures expose exact-context Play and Open in Spotify without fabricating unavailable tracks. Explicit linked playlist references, when requested, use the existing connection bundle and atomic lock. Reads merge all provider pages and linked references, deduplicate identities and paginate one projection. Disconnecting or replacing authorization clears the linked references; account and connection checks prevent assignment to another connection. Exact-link search never substitutes a similarly named public playlist.
