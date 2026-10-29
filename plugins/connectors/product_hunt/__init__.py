"""Portable manifest entry; backend services own credentials and transport."""


def register(ctx):
    from agent.plugins.product_hunt import product_hunt_plugin_status, product_hunt_service
    ctx.register_connector(id="app-69b7bed23a9481919d2378ab225cddeb", name="Product Hunt",
        category="Connectors", status_factory=product_hunt_plugin_status,
        service_factory=product_hunt_service, capabilities=["producthunt.read"])
