"""Vercel mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.vercel_connection import VercelMcpOperation, VercelOAuthRequest
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.vercel_connection import vercel_service


def vercel_contribution(*, service=None):
    def execute(payload, operation):
        current = service or vercel_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "oauth.start":
                flow = current.start(VercelOAuthRequest.model_validate(args))
                return {"changed": True, **flow.model_dump(), "_message": flow.message}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.vercel_mcp import VercelMcpAdapter
                return VercelMcpAdapter(service=current).execute(VercelMcpOperation.model_validate(args),
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
            from agent.plugins.vercel_connection import VercelError
            message = str(exc) if isinstance(exc, VercelError) else "Check the Vercel request fields and connection."
            raise PluginContributionActionError("VERCEL_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("oauth.start", "Sign in with Vercel", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel Vercel sign-in", "write", "none"),
        ("verify", "Verify Vercel connection", "read", "none"),
        ("disconnect", "Disconnect Vercel", "destructive", "operation_bound"),
        ("mcp", "Apply a Vercel change", "external_write", "operation_bound"),
    ):
        identifier = "vercel.mcp.execute" if operation == "mcp" else "vercel.connection." + operation
        schema = (VercelMcpOperation if operation == "mcp" else VercelOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="vercel", plugin_id="vercel",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="vercel.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="vercel", actions=tuple(actions))
