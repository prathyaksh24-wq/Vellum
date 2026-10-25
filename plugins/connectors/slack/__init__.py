"""Manifest entry; canonical backend owners handle Slack credentials and tools."""


def register(ctx):
    from agent.plugins.slack import slack_plugin_status, slack_service
    ctx.register_connector(id="slack", name="Slack", category="MCP", status_factory=slack_plugin_status,
        service_factory=slack_service, capabilities=["slack.mcp.execute"])
