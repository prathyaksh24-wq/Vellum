# YouTube Integration

Vellum treats YouTube as one portable connector with multiple evidence feeds.
The official Data API and Google Takeout do not become separate knowledge
systems.

## Ownership

| Feed | Purpose | Canonical identity |
| --- | --- | --- |
| Official OAuth | Channel identity and current subscriptions | YouTube channel ID |
| Google Takeout | Historical watch and search activity | Video ID plus event timestamp |
| Transcript ingestion | Video content evidence | YouTube video ID |
| Live search tools | Current query evidence | YouTube video or channel ID |

Knowledge Core owns imported source records and versions. Obsidian may receive
readable projections later, but projections are marked `do_not_reingest` and
never become a second source.

## OAuth Configuration

Use a Google OAuth client with application type **Desktop app** and enable the
YouTube Data API v3. Configure credentials only in the local `.env` file:

```env
YOUTUBE_OAUTH_CLIENT_ID=...
YOUTUBE_OAUTH_CLIENT_SECRET=...
YOUTUBE_OAUTH_ACCOUNT_LABEL=primary
```

Vellum requests only `youtube.readonly`. Google handles account selection and
consent in the browser. Vellum does not request an email scope and does not
store the primary email address. Access and refresh tokens are stored in the
operating-system keyring under `vellum.youtube`; Git-ignored runtime files hold
only non-secret channel metadata and short-lived PKCE state.

## Backend Contract

- `GET /api/plugins/youtube/status`
- `POST /api/plugins/youtube/oauth/start`
- `GET /api/plugins/youtube/oauth/callback`
- `POST /api/plugins/youtube/sync`
- `DELETE /api/plugins/youtube/connection`

Desktop authorization uses the Google-supported loopback redirect
`http://127.0.0.1:8000`; the API root forwards OAuth responses to the same
callback handler.

Subscription synchronization is a bounded full snapshot. Source identities are
stable and account-scoped, unchanged payloads do not create new versions, and
subscriptions missing from a later complete snapshot become inactive rather
than being deleted.

## Takeout Boundary

The YouTube Data API does not provide personal watch history or total watch
time. Those signals will be imported from Google Takeout after previewing the
actual archive layout. Takeout ingestion must be resumable, content-hashed, and
idempotent; it will join OAuth and transcript evidence by video/channel ID.
