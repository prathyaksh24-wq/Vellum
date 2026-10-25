"""GitHub manifest entry; canonical backend owners handle transport and grants."""


def register(ctx):
    from agent.plugins.github_connection import github_plugin_status, github_service
    ctx.register_connector(id="github", name="GitHub", category="Developer Tools", status_factory=github_plugin_status, service_factory=github_service)
