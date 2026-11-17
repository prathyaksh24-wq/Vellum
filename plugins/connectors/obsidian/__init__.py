"""Optional connector for a user's own Obsidian vault (Local REST API)."""


def register(ctx):
    from agent.plugins.obsidian import obsidian_plugin_status

    ctx.register_connector(
        id="obsidian",
        name="Obsidian",
        category="Connectors",
        status_factory=obsidian_plugin_status,
        capabilities=["obsidian.notes.read", "obsidian.notes.search", "obsidian.notes.write"],
    )
