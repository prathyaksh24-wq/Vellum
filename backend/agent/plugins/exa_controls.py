"""Exa mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.exa_connection import ExaMcpOperation, ExaOAuthRequest
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.exa_connection import exa_service


def exa_contribution(*, service=None):
    def execute(payload, operation):
        current = service or exa_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "oauth.start":
                flow = current.start(ExaOAuthRequest.model_validate(args))
                return {"changed": True, **flow.model_dump(), "_message": flow.message}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.exa_mcp import ExaMcpAdapter
                return ExaMcpAdapter(service=current).execute(ExaMcpOperation.model_validate(args),
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
            from agent.plugins.exa_connection import ExaError
            message = str(exc) if isinstance(exc, ExaError) else "Check the Exa request fields and connection."
            raise PluginContributionActionError("EXA_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("oauth.start", "Sign in with Exa", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel Exa sign-in", "write", "none"),
        ("verify", "Verify Exa connection", "read", "none"),
        ("disconnect", "Disconnect Exa", "destructive", "operation_bound"),
        ("mcp", "Apply a Exa change", "external_write", "operation_bound"),
    ):
        identifier = "exa.mcp.execute" if operation == "mcp" else "exa.connection." + operation
        schema = (ExaMcpOperation if operation == "mcp" else ExaOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="exa", plugin_id="exa",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="exa.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="exa", actions=tuple(actions))
