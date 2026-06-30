---
name: spotify
description: Control Spotify playback, devices, queue, search, playlists, albums, library, and recent listening history.
---

# Spotify tool-use rules

- Search once, choose the strongest exact match, then play its Spotify URI.
- Do not call `get_state` before an explicit pause, next, or previous command.
- List devices only when the user names a device or Spotify reports no active device.
- Treat an empty currently-playing response as a valid inactive state.
- Explain the Spotify Premium requirement only when a mutating action is rejected for that reason.
- Never expose tokens, Client IDs, authorization codes, local paths, or raw Spotify error bodies.
- Preserve the user's explicit shuffle, repeat, volume, device, playlist visibility, and collaborative settings.
