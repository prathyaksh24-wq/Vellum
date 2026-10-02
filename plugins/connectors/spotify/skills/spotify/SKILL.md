---
name: spotify
description: Control Spotify playback, songs, podcasts, playlists, saved tracks, devices, and queue.
---

# Spotify tool-use rules

- Search once, choose the strongest exact match, then play its Spotify URI.
- For a podcast, search `show` or `episode`, never `track`. Read a selected show's episodes with `spotify_podcasts` and play a playable episode URI. Ask which show when several names match; never replace a podcast request with a song.
- Treat "liked playlist" and "liked song playlist" as the saved-track library. A first/numbered-song request uses its one-based position and disables shuffle before playback.
- Preserve emoji playlist names. Search the full saved-playlist list; missing public matches require a choice. For a Daily Mix absent from that list, ask for its Spotify playlist link rather than substituting another user's mix.
- Treat complete next/skip phrases as playback controls. Ask about approximate song matches before playing; search ranking alone does not establish the requested title.
- Do not call `get_state` before an explicit pause, next, or previous command.
- For "like this song", "save this song", or "add this to Liked Songs", call `spotify_library` once with `kind=tracks` and `action=save_current`. Liked Songs is the user's library, not a playlist.
- After a successful playback or library mutation, acknowledge it in one short sentence. Do not claim a permission problem unless the tool returns an authorization error.
- List devices only when the user names a device or Spotify reports no active device.
- Treat an empty currently-playing response as a valid inactive state.
- Explain the Spotify Premium requirement only when a mutating action is rejected for that reason.
- Never expose tokens, Client IDs, authorization codes, local paths, or raw Spotify error bodies.
- Preserve the user's explicit shuffle, repeat, volume, device, playlist visibility, and collaborative settings.
