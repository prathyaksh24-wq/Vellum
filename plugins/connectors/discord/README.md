# Discord connector

Vellum connects through an installed Discord bot. It does not use user tokens or self-bot automation.

Live channel reads are restricted by `DISCORD_ALLOWED_GUILD_IDS` and
`DISCORD_ALLOWED_CHANNEL_IDS`. Every external write requires confirmation.

The connector requests View Channels, Read Message History, Send Messages,
Embed Links, Attach Files, Add Reactions, Use External Emojis, Create Public
Threads, and Send Messages in Threads. It requests no administrator,
message-management, moderation, role-management, channel-management, or
webhook-management permission. Vellum checks message authorship locally before
editing or deleting and will mutate only messages created by its own bot.

The built-in Discord intelligence sync reads the latest messages from each
allowlisted channel once per minute. Reads flow through the shared tool
observer into Knowledge Core as local-only evidence. It never posts, reacts,
edits, deletes, or creates threads in the background. Attachments sent by
Vellum are limited to 10 MiB and always require confirmation.
