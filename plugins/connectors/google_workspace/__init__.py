"""Google account connection is owned by the backend service."""


def register(ctx):
    from agent.plugins.google_workspace import google_service
    ctx.register_connector(id="google-workspace", name="Google", category="Connectors", service_factory=google_service)
