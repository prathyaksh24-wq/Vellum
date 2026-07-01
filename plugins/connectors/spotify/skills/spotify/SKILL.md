---
name: spotify
description: Control Spotify playback, devices, queue, search, playlists, albums, library, and recent listening history.
---

# Spotify tool-use rules

- Search once, choose the strongest exact match, then play its Spotify URI.
- Do not call `get_state` before an explicit pause, next, or previous command.
- For "like this song", "save this song", or "add this to Liked Songs", call `spotify_library` once with `kind=tracks` and `action=save_current`. Liked Songs is the user's library, not a playlist.
- After a successful playback or library mutation, acknowledge it in one short sentence. Do not claim a permission problem unless the tool returns an authorization error.
- List devices only when the user names a device or Spotify reports no active device.
- Treat an empty currently-playing response as a valid inactive state.
- Explain the Spotify Premium requirement only when a mutating action is rejected for that reason.
- Never expose tokens, Client IDs, authorization codes, local paths, or raw Spotify error bodies.
- Preserve the user's explicit shuffle, repeat, volume, device, playlist visibility, and collaborative settings.
