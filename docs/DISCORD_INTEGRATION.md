# Discord integration

Vellum uses an installed Discord bot. It does not automate a normal Discord
account and does not accept user tokens, passwords, or browser cookies.

## Configuration

Store credentials and policy in the repository `.env` file. Never commit that
file.

```env
DISCORD_APPLICATION_ID=...
DISCORD_BOT_TOKEN=...
DISCORD_ALLOWED_GUILD_IDS=...
DISCORD_ALLOWED_CHANNEL_IDS=...
DISCORD_INTELLIGENCE_SYNC_ENABLED=true
```

ID lists are comma-separated Discord snowflake IDs. The policy fails closed:

- The bot can discover its installed servers, but channel enumeration requires
  the server ID in `DISCORD_ALLOWED_GUILD_IDS`.
- Reading messages requires the channel ID in `DISCORD_ALLOWED_CHANNEL_IDS`.
- Every send, reply, edit, delete, reaction, thread action, and attachment
  requires explicit confirmation.

Restart Vellum after changing these values because settings and agent catalogs
are process-scoped.

## Installation

Open Vellum's Plugins screen, select Discord, and choose **Install bot**. The
backend generates the Discord authorization URL with the requested permissions.
The URL requests View Channels, Read Message History, Send Messages, Embed Links,
Attach Files, Add Reactions, Use External Emojis, Create Public Threads, and Send
Messages in Threads. Do not grant Administrator, Manage Messages, moderation,
role-management, channel-management, webhook-management, or unrelated permissions.

The connector supports bot identity, installed server discovery, allowlisted
channel discovery, recent message reads, text and attachment sends, replies,
reactions, public threads, and editing or deleting only Vellum's own messages.
Every external write requires confirmation. Historical data-package ingestion is
separate and can be added when an export is available.

The built-in Discord intelligence sync polls allowlisted channels once per minute
and stores message sources through the Knowledge Core tool observer. Source
identity makes repeated reads idempotent. Pause the built-in automation or set
`DISCORD_INTELLIGENCE_SYNC_ENABLED=false` to disable it.

## API

- `GET /api/plugins/discord/status`
- `GET /api/plugins/discord/install`
- `GET /api/plugins/discord/guilds`
- `GET /api/plugins/discord/guilds/{guild_id}/channels`
- `GET /api/plugins/discord/channels/{channel_id}/messages`
- `POST /api/plugins/discord/channels/{channel_id}/messages`
- `POST /api/plugins/discord/channels/{channel_id}/attachments`
- `POST /api/plugins/discord/channels/{channel_id}/messages/{message_id}/reply`
- `PATCH /api/plugins/discord/channels/{channel_id}/messages/{message_id}`
- `POST /api/plugins/discord/channels/{channel_id}/messages/{message_id}/delete`
- `POST /api/plugins/discord/channels/{channel_id}/messages/{message_id}/reactions`
- `POST /api/plugins/discord/channels/{channel_id}/messages/{message_id}/threads`
- `POST /api/plugins/discord/channels/{channel_id}/threads/{thread_id}/messages`

Read message results enter Knowledge Core as private local-only evidence with raw
external egress denied. Agent-initiated reads are observations, not evidence that
the user agrees with or prefers the message content. DiscordAgent responses pass
directly through the local dispatcher; the fallback main-model tool exposes only
status metadata and never raw message content.
