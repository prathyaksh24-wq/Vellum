"""Zomato mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.zomato_connection import ZomatoMcpOperation, ZomatoOAuthRequest
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.zomato_connection import zomato_service


def zomato_contribution(*, service=None):
    def execute(payload, operation):
        current = service or zomato_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "oauth.start":
                flow = current.start(ZomatoOAuthRequest.model_validate(args))
                return {"changed": True, **flow.model_dump(), "_message": flow.message}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.zomato_mcp import ZomatoMcpAdapter
                return ZomatoMcpAdapter(service=current).execute(ZomatoMcpOperation.model_validate(args),
                    binding=payload.get("confirmation_binding"), confirmed=payload.get("confirmed") is True)
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
            from agent.plugins.zomato_connection import ZomatoError
            message = str(exc) if isinstance(exc, ZomatoError) else "Check the Zomato request fields and connection."
            raise PluginContributionActionError("ZOMATO_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("oauth.start", "Sign in with Zomato", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel Zomato sign-in", "write", "none"),
        ("verify", "Verify Zomato connection", "read", "none"),
        ("disconnect", "Disconnect Zomato", "destructive", "operation_bound"),
        ("mcp", "Apply a Zomato change", "external_write", "operation_bound"),
    ):
        identifier = "zomato.mcp.execute" if operation == "mcp" else "zomato.connection." + operation
        schema = (ZomatoMcpOperation if operation == "mcp" else ZomatoOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="zomato", plugin_id="zomato",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="zomato.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="zomato", actions=tuple(actions))
