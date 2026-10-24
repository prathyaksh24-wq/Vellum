"""Contact reads share the Google account connection."""


def register(ctx):
    ctx.register_connector(id="google-contacts", name="Google Contacts", category="Connectors")
