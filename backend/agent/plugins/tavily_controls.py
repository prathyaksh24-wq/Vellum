"""Tavily mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.tavily_connection import TavilyMcpOperation, TavilyOAuthRequest
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.tavily_connection import tavily_service


def tavily_contribution(*, service=None):
    def execute(payload, operation):
        current = service or tavily_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "oauth.start":
                flow = current.start(TavilyOAuthRequest.model_validate(args))
                return {"changed": True, **flow.model_dump(), "_message": flow.message}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.tavily_mcp import TavilyMcpAdapter
                return TavilyMcpAdapter(service=current).execute(TavilyMcpOperation.model_validate(args),
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
            from agent.plugins.tavily_connection import TavilyError
            message = str(exc) if isinstance(exc, TavilyError) else "Check the Tavily request fields and connection."
            raise PluginContributionActionError("TAVILY_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("use_configured", "Use configured Tavily API credential", "write", "none"),
        ("oauth.start", "Sign in with Tavily", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel Tavily sign-in", "write", "none"),
        ("verify", "Verify Tavily connection", "read", "none"),
        ("disconnect", "Disconnect Tavily", "destructive", "operation_bound"),
        ("mcp", "Apply a Tavily change", "external_write", "operation_bound"),
    ):
        identifier = "tavily.mcp.execute" if operation == "mcp" else "tavily.connection." + operation
        schema = (TavilyMcpOperation if operation == "mcp" else TavilyOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="tavily", plugin_id="tavily",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="tavily.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="tavily", actions=tuple(actions))
