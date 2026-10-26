"""Apify mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.apify_connection import ApifyMcpOperation, ApifyOAuthRequest
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.apify_connection import apify_service


def apify_contribution(*, service=None):
    def execute(payload, operation):
        current = service or apify_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "oauth.start":
                flow = current.start(ApifyOAuthRequest.model_validate(args))
                return {"changed": True, **flow.model_dump(), "_message": flow.message}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.apify_mcp import ApifyMcpAdapter
                return ApifyMcpAdapter(service=current).execute(ApifyMcpOperation.model_validate(args),
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
            from agent.plugins.apify_connection import ApifyError
            message = str(exc) if isinstance(exc, ApifyError) else "Check the Apify request fields and connection."
            raise PluginContributionActionError("APIFY_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("use_configured", "Use configured Apify API credential", "write", "none"),
        ("oauth.start", "Sign in with Apify", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel Apify sign-in", "write", "none"),
        ("verify", "Verify Apify connection", "read", "none"),
        ("disconnect", "Disconnect Apify", "destructive", "operation_bound"),
        ("mcp", "Apply an Apify change", "external_write", "operation_bound"),
    ):
        identifier = "apify.mcp.execute" if operation == "mcp" else "apify.connection." + operation
        schema = (ApifyMcpOperation if operation == "mcp" else ApifyOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="apify", plugin_id="apify",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="apify.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="apify", actions=tuple(actions))
