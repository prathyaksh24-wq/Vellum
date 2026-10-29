---
name: spotify
description: Control Spotify playback, songs, podcasts, playlists, saved tracks, devices, and queue.
---

# Spotify tool-use rules

- Search the exact title first. If missing, make at most one broad catalog query and rank candidates deterministically. A strong typo match with an explicit artist can resolve directly; ambiguous titles or versions require a selection. Play the resolved Spotify URI.
- For a podcast, search `show` or `episode`, never `track`. Read a selected show's episodes with `spotify_podcasts` and play a playable episode URI. Ask which show when several names match; never replace a podcast request with a song.
- Treat "liked playlist" and "liked song playlist" as the saved-track library. A first/numbered-song request uses its one-based position and disables shuffle before playback.
- Resolve playlists from the full saved-playlist list or an explicit Spotify link. Preserve emoji names; "emoji playlist" requires a choice when multiple symbol-only names match. Never substitute public playlists for missing personal playlists. For a Daily Mix absent from the list, ask for its Spotify link.
- Suggestions wait for acceptance. Use the captured song queue or exact playlist identity; do not search again on acceptance or infer a most-used playlist. Report when a bounded queue has no further songs.
- Current-song questions read live state, never prior acknowledgements. For Vellum volume, use the existing playback control and require the SDK's measured acknowledgement; do not claim success from an optimistic slider value.
- Treat complete next/skip phrases as playback controls. Ask about approximate song matches before playing; search ranking alone does not establish the requested title.
- Do not call `get_state` before an explicit pause, next, or previous command.
- Clear song add/remove instructions authorize that song and destination without another confirmation. MusicAgent captures the current track or resolves an explicit title, checks membership, makes one write, then verifies membership before acknowledging success. Named removals resolve against the actual destination collection, including bounded typo matching; never substitute a public search result for a saved song. Ask which target only when ambiguous. Liked Songs is the user's library, not a playlist.
- For an artist's latest album, resolve the artist, read all bounded `spotify_albums` artist_albums pages with include_groups=album, and compare release dates. Exclude singles, appearances and future releases; fail visibly if the catalog cannot be checked completely. Start the album context once and verify the currently-playing context before claiming playback.
- After a successful playback or library mutation, acknowledge it in one short sentence. Do not claim a permission problem unless the tool returns an authorization error.
- List devices only when the user names a device or Spotify reports no active device.
- Treat an empty currently-playing response as a valid inactive state.
- Explain the Spotify Premium requirement only when a mutating action is rejected for that reason.
- Never expose tokens, Client IDs, authorization codes, local paths, or raw Spotify error bodies.
- Preserve the user's explicit shuffle, repeat, volume, device, playlist visibility, and collaborative settings.
