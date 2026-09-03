# Discord connector

Vellum connects through an installed Discord bot. It does not use user tokens or self-bot automation.

Live channel reads are restricted by `DISCORD_ALLOWED_GUILD_IDS` and
`DISCORD_ALLOWED_CHANNEL_IDS`. External writes require confirmation unless the
target channel is also listed in `DISCORD_AUTONOMOUS_CHANNEL_IDS`.

The connector requests only View Channels, Read Message History, and Send
Messages. It requests no administrator, message-management, attachment,
reaction, thread, or slash-command permission.
