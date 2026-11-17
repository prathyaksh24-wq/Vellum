# Obsidian

Optional connector for your own Obsidian vault. Vellum keeps its memory and
knowledge in the Knowledge Core; this connector only lets the agent work with
notes in a vault you choose to connect.

## Setup

1. In Obsidian, install and enable the **Local REST API** community plugin.
2. Copy its API key into `.env` as `OBSIDIAN_API_KEY`.
3. Enable **Obsidian** in Vellum's Plugins.

`OBSIDIAN_MCP_URL` defaults to `https://127.0.0.1:27124/mcp/`. Reads are always
allowed once connected. Writes, deletes and Obsidian commands stay off unless
you set `OBSIDIAN_MCP_ALLOW_WRITES`, `OBSIDIAN_MCP_ALLOW_DESTRUCTIVE` or
`OBSIDIAN_MCP_ALLOW_COMMANDS` to `true`.
