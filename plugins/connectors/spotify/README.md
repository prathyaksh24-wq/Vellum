# Spotify Connector

Hermes-compatible portable plugin providing full Spotify Web API control in Vellum.

## Setup

1. Create a Spotify application at `https://developer.spotify.com/dashboard`.
2. Enable Web API and Web Playback SDK.
3. Register this redirect URI:

   `http://127.0.0.1:8000/api/plugins/spotify/oauth/callback`

4. In Vellum, open Settings → Plugins → Spotify, enter the public Client ID, and approve access.

PKCE is used, so no client secret is required. Credentials are stored locally at `data/plugins/spotify/auth.json` and are never exposed to the model.

If your account was connected before embedded playback was added, open the Spotify player and choose **Allow playback in Vellum**. Leave Client ID blank to reuse the existing app. Approve the new `streaming` and `user-read-email` scopes (the SDK also requires `user-read-private`).

Open the Spotify player, then click **Enable playback in Vellum** once to activate browser audio. After **Vellum player ready**, typed requests use the existing Spotify tools to search and play music on the registered **Vellum** Connect device. Neither Spotify Desktop nor Spotify's web player needs to be open. Keep the Vellum window open and the computer awake while listening; this is online streaming directly from Spotify.

## Embedded playback lifecycle

Open the UI through the local frontend server at `http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html`. Direct `file://` HTML previews cannot receive SDK credentials because their `null` origin cannot be distinguished from an untrusted local file. The player offers a link to the served UI instead of asking for Spotify consent again.

The portable plugin's cached service owns the active Vellum device. Existing playback and queue tools default to this device; an explicit `device_id` remains supported. While Vellum playback is selected but unavailable, tools return a readiness error instead of switching to another device. Disable Vellum playback to return to the existing external-device controls.

`spotify.playback.session` is a typed, UI-only App Action for enabling/disabling the runtime. The SDK's `activateElement()` is invoked synchronously from the click before dispatch. Device registration, offline notifications and 20-second heartbeats are internal runtime lifecycle events, not user controls or stored preferences. They use typed API contracts and expire after 90 seconds. Only one window owns playback; another window must wait until the owner releases or expires. The local API runs as one process, as in the standard launcher.

Player buttons and quick typed controls such as `pause Spotify` use `spotify.playback.control` in the existing App Action runtime. A bare `pause` is recognized as music control only while this Vellum player is selected. Overlapping identical button requests are coalesced; conflicting controls are rejected until the current request finishes. No automatic replay follows an uncertain network failure.

Song, podcast, and playlist requests delegate to **MusicAgent** through the existing catalog and typed delegation runtime. Examples include `play Blinding Lights`, `Blinding Lights by The Weeknd on Spotify`, and `from my Hindi playlist play a song in shuffle order`. MusicAgent exclusively owns the Spotify skill and eight raw plugin tools; the UI retains its typed controls and SDK lifecycle access. The main agent sees the MusicAgent directory entry and delegates music work instead of discovering raw Spotify tools. Music requests also delegate when an unrelated specialist was previously selected, without changing that explicit selection. Playback responses bypass a second model rewrite and are never replayed from a specialist cache.

The provider-neutral `MusicPlan` and `MusicIntegration` interface allow another music service to supply an adapter and approved capabilities later. Only Spotify is connected now; requesting an unavailable service returns a connection limitation. Direct commands resolve without a model round trip. Less direct commands are parsed by the current local model into a schema-validated plan before any tool executes. Credentials, listening history and unrelated conversations do not enter that planner. Spotify reads are excluded from automatic Knowledge Core tool observation; explicit user preferences remain governed by the existing memory policies.

`play the next song` and `skip this song` are controls, not song searches. Playback-only turns are saved to the existing conversation checkpoint with their own acknowledgement. An ambiguous title offers artist choices before playback; `from Twenty One Pilots` or the artist's name applies to the preceding request using the shared thread context, expiring after 30 minutes and isolated by conversation. This context is not a learned listening profile.

`play something from my Kannada playlist` resolves a unique matching playlist name, including names such as `Kannada bangers`. Multiple matches require clarification. Shuffle starts at a random playlist position. `play something from my Liked Songs` reads saved tracks rather than looking for a playlist named Liked Songs; it plays a bounded queue of up to 50 saved tracks, choosing a random library window for larger collections. The player refreshes its queue while open, takes upcoming-track updates from the SDK, and shows distinct upcoming tracks instead of copies of the current track. It shows an empty queue truthfully when Spotify supplies no upcoming tracks.

Named playlist matching applies to other playlists too. To create one, type `create a playlist called Night Drive with Blinding Lights by The Weeknd, As It Was by Harry Styles`. MusicAgent searches and previews the actual tracks before any write. Reply `confirm` to create the private playlist or `cancel` to discard the proposal. The existing pending-action store binds that approval to this conversation and consumes it once. Up to 50 requested songs are supported; missing names or song choices require clarification. A failed or uncertain write is reported honestly and is not retried automatically. The portable connector uses Spotify's current `POST /me/playlists` endpoint and the existing add-items endpoint.

`play the 1st song from the liked song playlist` uses Liked Songs in library order, with shuffle disabled before playback. `play something from my liked playlist` shuffles saved tracks. Playlist matching preserves emoji symbols (including emoji-only names), ignores presentation selectors, and paginates beyond 500 entries. A missing saved playlist can offer public search choices, which require selection before playback. Daily Mixes absent from Spotify's saved-playlist response require their Spotify link; public playlists with the same name are not substituted for a personal mix. Spotify playlist links and URIs work directly and as follow-ups without a metadata preflight, since personalized mixes can return metadata 404 while still allowing playback. A link supplied after a named-playlist request binds that name to the URI in the existing thread context (at most five links, isolated by conversation, expiring after 30 minutes without a music turn); it creates no global alias store or listening profile.

`play a podcast from Nikhil Kamath` searches shows and starts the first playable episode returned by Spotify. `play a podcasts from WTF` asks which matching show; reply with its name or offered number. These choices use the existing bounded specialist context. Podcasts never fall back to music searches, and the SDK/player accepts episode metadata without song artist/album fields. Episode playback is subject to Spotify's actual device/content restrictions; a rejected command is reported as an error.

The current device lease retains at most 32 health observations (SDK event name, relative timestamp, paused state, position and volume) and playback command counts. These appear as `web_playback` in the existing player response, contain no credentials, song metadata or conversation text, and disappear when the session is released or the API restarts. They help distinguish player errors and reconnects from duplicate commands; they do not prove sound reached the speakers.

The SDK requests a fresh access token through the trusted local UI adapter whenever it needs one. Only the access token reaches the SDK, in memory; refresh tokens stay in the existing local store. The token endpoint checks client, Host, approved UI Origin and a non-simple header and returns `Cache-Control: no-store`. It is absent from model tool discovery and action receipts. SDK-rejected tokens trigger a refresh with a one-minute cooldown; repeated authentication failures require consent again. Connections have a timeout and exponential retry delay. Unsupported protected audio, Premium/account errors and autoplay rejection are shown explicitly.

Windows desktop uses Tauri/WebView2. Spotify documents browser support, not a guarantee for WebView2. Native protected-audio compatibility must pass a real playback check on the installed runtime; a successful frontend build or mock SDK test does not establish it. If initialization fails, Vellum reports the unsupported runtime. The browser-hosted Vellum UI can also use the same player on Spotify-supported browsers, but native desktop playback remains a separate acceptance gate.

Live acceptance: reconnect with the SDK scopes; keep Spotify closed; enable Vellum playback; play a track from typed chat; test pause/next and playlist shuffle; leave it running across token expiry; test network loss and sleep/wake; close/reopen Vellum and re-enable browser audio. Automated tests cover device routing, lease expiry/ownership, token refresh and lifecycle recovery. They do not prove audible playback or days/months of uptime.

Sources: [SDK reference](https://developer.spotify.com/documentation/web-playback-sdk/reference), [SDK setup](https://developer.spotify.com/documentation/web-playback-sdk/howtos/web-app-player), [WebView2 Widevine feedback](https://github.com/MicrosoftEdge/WebView2Feedback/issues/4828).

## Tools

- `spotify_playback`
- `spotify_devices`
- `spotify_queue`
- `spotify_search`
- `spotify_playlists`
- `spotify_albums`
- `spotify_library`
- `spotify_podcasts`

Spotify Free supports search and read-oriented library features. Premium is required for playback mutations, queue additions, and device transfer. The embedded SDK supplies Vellum's Connect device; external-device mode requires another active Spotify device.
