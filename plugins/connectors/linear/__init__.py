"""Manifest entry; the backend owns Linear transport and credentials."""


def register(ctx):
    from agent.plugins.linear import linear_plugin_status, linear_service
    ctx.register_connector(id="linear", name="Linear", category="MCP",
        status_factory=linear_plugin_status, service_factory=linear_service,
        capabilities=["linear.mcp.read", "linear.mcp.tools", "linear.mcp.execute"])
