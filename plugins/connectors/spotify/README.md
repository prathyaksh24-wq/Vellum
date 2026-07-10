# Spotify Connector

Hermes-compatible portable plugin providing full Spotify Web API control in Vellum.

## Setup

1. Create a Spotify application at `https://developer.spotify.com/dashboard`.
2. Enable the Web API.
3. Register this redirect URI:

   `http://127.0.0.1:8000/api/plugins/spotify/oauth/callback`

4. In Vellum, open Settings → Plugins → Spotify, enter the public Client ID, and approve access.

PKCE is used, so no client secret is required. Credentials are stored locally at `data/plugins/spotify/auth.json` and are never exposed to the model.

## Tools

- `spotify_playback`
- `spotify_devices`
- `spotify_queue`
- `spotify_search`
- `spotify_playlists`
- `spotify_albums`
- `spotify_library`

Spotify Free supports search and read-oriented library features. Premium is required for playback mutations, queue additions, and device transfer. Playback control also requires at least one active Spotify Connect device.
