# Vellum Spotify Plugin Design

Date: 2026-06-29
Status: Approved for implementation planning

## Goal

Ship a real Spotify integration as a portable Vellum plugin. After one-time setup, the user can ask Vellum to play, pause, skip, seek, change volume, manage the queue, move playback between devices, search Spotify, and manage playlists and saved music. The feature targets full parity with the seven Spotify tool groups documented by Hermes.

## Constraints

- Follow the Hermes general-plugin contract: `plugin.yaml`, schemas, handlers, and `register(ctx)`.
- Load that contract through Vellum's portable-plugin wrapper; Hermes is not a runtime dependency.
- Spotify is globally available after authentication. It is not selected per chat.
- Modify only `design/Velllum/uploads/Vellum Default Re-designed.html` for UI work. Backend, plugin, test, and documentation files may be added or changed as required.
- Use Spotify's official Web API and Authorization Code with PKCE. Do not require or store a client secret.
- Preserve Vellum's privacy gate, audit rules, and local credential storage.

## Architecture

The integration has four boundaries:

1. **Portable plugin** — declares Spotify tools using the Hermes schema/handler/registration pattern.
2. **Vellum adapter** — extends `PortablePluginContext` with `register_tool()` and converts registered schemas and handlers into LangChain-callable tools.
3. **Spotify service** — owns PKCE, token persistence/refresh, HTTP calls, normalization, and Spotify-specific errors.
4. **UI/API surface** — provides guided setup, connection status, and direct player controls while natural-language commands continue through the agent.

The agent receives Spotify tools only when the plugin is enabled and authenticated. A connection-state change invalidates Vellum's lazy agent instance so the next turn rebuilds its tool list. This avoids sending unusable Spotify schemas on every model call before setup.

## Plugin layout

```text
plugins/connectors/spotify/
├── plugin.yaml
├── __init__.py
├── schemas.py
├── tools.py
├── client.py
├── auth.py
├── errors.py
├── README.md
└── skills/spotify/SKILL.md
```

- `plugin.yaml` is a compatible superset: it includes Hermes fields such as `name`, `version`, and `provides_tools`, plus Vellum's `id`, `type`, `category`, and `capabilities` metadata. Each runtime ignores fields it does not consume.
- `schemas.py` contains the seven Hermes-compatible JSON tool schemas.
- `tools.py` exposes handlers with `handler(args: dict, **kwargs) -> str`. Every result, including errors, is a JSON string.
- `__init__.py` calls `ctx.register_tool(...)` for each tool and registers connector status metadata.
- `client.py` contains the Spotify Web API client and response normalization.
- `auth.py` implements PKCE, local flow state, token storage, refresh, and logout.
- The bundled skill teaches canonical behavior such as search once then play, avoiding unnecessary playback-state preflights, and resolving devices by display name.

## Tool surface

The plugin exposes the same seven groups as Hermes:

- `spotify_playback`: state, currently playing, history, play, pause, next, previous, seek, repeat, shuffle, and volume.
- `spotify_devices`: list and transfer.
- `spotify_queue`: inspect and add.
- `spotify_search`: tracks, albums, artists, playlists, shows, and episodes.
- `spotify_playlists`: list, get, create, add/remove items, and update details.
- `spotify_albums`: album metadata and tracks.
- `spotify_library`: list, save, and remove tracks or albums.

Playback mutations, queue additions, and device transfer require Spotify Premium. Read-only operations remain available to Free accounts. Low-risk playback mutations do not require a second Vellum confirmation after an explicit user request. Ambiguous destructive library or playlist changes are not executed until intent is clear.

## Authentication and local storage

The Plugins UI presents a guided setup:

1. Explain that the user needs a Spotify developer application.
2. Show the exact redirect URI and open Spotify's developer dashboard.
3. Accept the public Client ID.
4. Start PKCE authorization in the browser.
5. Handle the localhost callback, exchange the code, and display the connected account.

Default callback:

```text
http://127.0.0.1:8000/api/plugins/spotify/oauth/callback
```

Persistent data lives under `data/plugins/spotify/`:

- `auth.json`: Client ID, access token, refresh token, expiry, granted scopes, and redirect URI.
- `oauth-flow.json`: short-lived state and code verifier; removed after success or expiry.

Writes are atomic. Tokens and authorization response bodies never enter prompts, tool results, UI state, or the content-free audit log. A Spotify 401 triggers one refresh-and-retry. A failed refresh changes the connector state to `reauth_required`.

## Backend API

- `GET /api/plugins/spotify/status` — configuration, account display name, product tier, scopes, and current device summary; never returns tokens.
- `POST /api/plugins/spotify/oauth/start` — validates the Client ID, creates PKCE state, and returns the authorization URL.
- `GET /api/plugins/spotify/oauth/callback` — validates state, exchanges the code, stores tokens, and notifies the opener window.
- `POST /api/plugins/spotify/logout` — removes local Spotify credentials and invalidates the agent tool cache.
- `GET /api/plugins/spotify/player` — normalized now-playing state for the compact player.
- `POST /api/plugins/spotify/player/action` — allow-listed direct UI controls such as play, pause, next, previous, seek, volume, shuffle, repeat, and transfer.

The direct-control endpoint delegates to the same plugin service used by tool handlers so behavior and error mapping cannot diverge.

## Agent integration

Vellum's portable context gains Hermes-compatible tool registration. Registered tools are validated for unique names and valid schemas, wrapped as LangChain tools, and appended to both synchronous and asynchronous agent builders.

Spotify remains globally routable after connection. The system prompt gets a short generated tool summary rather than hard-coded Spotify implementation details. The bundled skill supplies selection patterns only for turns where Spotify intent is detected.

User text still passes Vellum's local privacy classification and scrubbing pipeline before reaching OpenRouter. Public catalog entities such as artist, album, and track names are treated as query data rather than user PII. Personal context remains protected. Spotify credentials and local filesystem paths are never exposed to OpenRouter.

## UI design

Only `design/Velllum/uploads/Vellum Default Re-designed.html` changes.

The existing Plugins settings section gains a Spotify row with disconnected, connecting, connected, and reauthentication states. Selecting Connect opens the guided setup modal. Connected state shows the account and a Disconnect action.

A compact global Spotify pill appears in the title bar when connected. It shows artwork, track and artist, play/pause, and next. Selecting it opens a panel containing previous/next, progress and seek, volume, shuffle, repeat, device transfer, and a short queue preview. Natural-language control remains the primary interface; the player provides immediate feedback and common direct actions.

The player polls only while Spotify is connected and the Vellum window is visible. It backs off when playback is inactive or Spotify rate-limits requests.

## Error behavior

- No active device: tell the user to open Spotify on a device and retry; show available devices when possible.
- Premium required: identify the unsupported action without failing unrelated read operations.
- Nothing playing / HTTP 204: return a successful inactive state.
- Unauthorized: refresh once, then require reconnection.
- Rate limited / HTTP 429: honor `Retry-After`, stop UI polling temporarily, and return a concise retry message.
- Network or Spotify outage: return a sanitized unavailable result; never include response bodies containing credentials.
- Plugin load failure: disable Spotify and leave Vellum operational.

## Verification

Tests cover:

- Manifest discovery and Hermes-compatible `register_tool()` behavior.
- Dynamic inclusion and removal of Spotify tools in both agent builders.
- Every tool action's schema, validation, normalized success result, and sanitized error result.
- PKCE state validation, callback persistence, logout, expiry, refresh-and-retry, and revoked refresh tokens.
- Free versus Premium behavior, no-active-device 403, empty 204, and rate-limit 429.
- Privacy and audit assertions proving tokens, Client IDs, raw authorization responses, and local paths are absent.
- API status/auth/player endpoints.
- UI connection states, popup completion, compact-player controls, visibility-aware polling, and responsive layout.
- An end-to-end mocked flow: connect, ask Vellum to search and play a track, pause, skip, transfer devices, modify a playlist, and inspect saved music.

## Acceptance criteria

- A user can connect Spotify entirely from Vellum using only a Spotify Client ID.
- After connection, natural-language Spotify commands work in every chat without selecting an app.
- All seven Hermes Spotify tool groups are implemented.
- Playback state and common controls are available globally in the specified HTML UI.
- Credentials remain local and never enter model or audit payloads.
- Spotify failures are actionable and do not destabilize Vellum.
- The plugin can be packaged independently while using Vellum's wrapper at runtime.

## Non-goals

- Audio streaming through Vellum itself.
- Replacing the Spotify client or Spotify Connect.
- Supporting Spotify client-secret OAuth.
- Adding Spotify ingestion to the Obsidian vault.
- Scheduling Spotify actions in the first implementation; existing automation support may call the tools later.
