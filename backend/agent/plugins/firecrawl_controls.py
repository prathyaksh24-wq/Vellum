"""Firecrawl mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.firecrawl_connection import FirecrawlMcpOperation, FirecrawlOAuthRequest
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.firecrawl_connection import firecrawl_service


def firecrawl_contribution(*, service=None):
    def execute(payload, operation):
        current = service or firecrawl_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "oauth.start":
                flow = current.start(FirecrawlOAuthRequest.model_validate(args))
                return {"changed": True, **flow.model_dump(), "_message": flow.message}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.firecrawl_mcp import FirecrawlMcpAdapter
                return FirecrawlMcpAdapter(service=current).execute(FirecrawlMcpOperation.model_validate(args),
                    binding=payload.get("confirmation_binding"), confirmed=payload.get("confirmed") is True)
            elif operation == "use_configured":
                if args:
                    raise ValueError()
                status = current.use_configured()
            else:
                if args:
                    raise ValueError()
                if operation == "disconnect":
                    if payload.get("confirmed") is not True:
                        raise ValueError()
                    status = current.disconnect()
                else:
                    status = current.verify()
            return {"changed": operation in {"disconnect", "use_configured"}, "connection": status.model_dump(), "_message": status.message}
        except (ValueError, RuntimeError) as exc:
            from agent.plugins.firecrawl_connection import FirecrawlError
            message = str(exc) if isinstance(exc, FirecrawlError) else "Check the Firecrawl request fields and connection."
            raise PluginContributionActionError("FIRECRAWL_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("use_configured", "Use configured Firecrawl API credential", "write", "none"),
        ("oauth.start", "Sign in with Firecrawl", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel Firecrawl sign-in", "write", "none"),
        ("verify", "Verify Firecrawl connection", "read", "none"),
        ("disconnect", "Disconnect Firecrawl", "destructive", "operation_bound"),
        ("mcp", "Apply a Firecrawl change", "external_write", "operation_bound"),
    ):
        identifier = "firecrawl.mcp.execute" if operation == "mcp" else "firecrawl.connection." + operation
        schema = (FirecrawlMcpOperation if operation == "mcp" else FirecrawlOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="firecrawl", plugin_id="firecrawl",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="firecrawl.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="firecrawl", actions=tuple(actions))
