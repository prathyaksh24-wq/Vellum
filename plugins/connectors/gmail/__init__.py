"""Gmail reads share the Google account connection."""


def register(ctx):
    ctx.register_connector(id="gmail", name="Gmail", category="Connectors")
