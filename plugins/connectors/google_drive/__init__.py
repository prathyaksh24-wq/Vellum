"""Drive reads share the Google account connection."""


def register(ctx):
    ctx.register_connector(id="google-drive", name="Google Drive", category="Connectors")
