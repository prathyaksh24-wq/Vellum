# YouTube Integration

Vellum treats YouTube as one portable connector with multiple evidence feeds.
The official Data API and Google Takeout do not become separate knowledge
systems.

## Ownership

| Feed | Purpose | Canonical identity |
| --- | --- | --- |
| Official OAuth | Channel identity, current subscriptions, and recent liked videos | YouTube channel ID |
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

## Query Routing

Provider ownership is deterministic:

- Connection, account, channel identity, and personal subscription questions
  use the official OAuth connector through `youtube.account` or
  `youtube.subscriptions`.
- Recent liked-video questions use the authenticated account's related likes
  playlist through `youtube.liked_videos`.
- Imported watch and search questions use private Knowledge Core observations
  through `youtube.takeout_history` and never pass through the external model.
- Public video discovery uses `youtube.search_videos`, where SerpAPI is the
  preferred search provider.
- Transcript requests use `youtube.fetch_transcript`, where SerpAPI may provide
  the transcript before local-card fallback.

Account and subscription questions never fall back to public web or SerpAPI
search. A disconnected or unavailable OAuth connector is reported directly.
The same rule applies to liked videos and Takeout history. `YoutubeAgent`
bypasses the generic specialist response cache so account and archive changes
are visible immediately.

The official API does not expose the personalized subscriptions feed. Vellum
reports that boundary through `youtube.subscription_feed`; it does not replace
the requested private feed with SerpAPI results. A complete feed requires a
separate scheduled, quota-aware poll of each subscribed channel's uploads.

Desktop authorization uses the Google-supported loopback redirect
`http://127.0.0.1:8000`; the API root forwards OAuth responses to the same
callback handler.

Subscription synchronization is a bounded full snapshot. Source identities are
stable and account-scoped, unchanged payloads do not create new versions, and
subscriptions missing from a later complete snapshot become inactive rather
than being deleted.

## Takeout Boundary

The YouTube Data API does not provide personal watch history or total watch
time. Those signals are imported from Google Takeout through a resumable,
content-hashed, idempotent job and joined to OAuth and transcript evidence by
video/channel ID.

Large entries under `YouTube and YouTube Music/videos/` are exported media,
not watch-history events. The Takeout importer must inventory and content-hash
their metadata without extracting, duplicating, embedding, or ingesting raw
media. Media analysis is a separate explicit workflow. Watch/search history
files in other Takeout parts remain the source for behavioral timelines.

Import an archive locally with:

```powershell
& .\.venv\Scripts\python.exe scripts\import_youtube_takeout.py "D:\path\to\takeout.zip"
```

The importer hashes the archive, parses activity cards by their actual URL type
rather than trusting the containing filename, normalizes timestamps to UTC,
and bulk-inserts private observations transactionally. Archive media stays in
place; only entry name, byte size, and CRC metadata are inventoried. Repeating
an idempotency key does not execute the import again, and stable event keys
deduplicate activity repeated across Takeout files.
