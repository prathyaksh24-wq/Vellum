"""ClickUp mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.clickup_connection import ClickUpMcpOperation, ClickUpOAuthRequest
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.clickup_connection import clickup_service


def clickup_contribution(*, service=None):
    def execute(payload, operation):
        current = service or clickup_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "oauth.start":
                flow = current.start(ClickUpOAuthRequest.model_validate(args))
                return {"changed": True, **flow.model_dump(), "_message": flow.message}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.clickup_mcp import ClickUpMcpAdapter
                return ClickUpMcpAdapter(service=current).execute(ClickUpMcpOperation.model_validate(args),
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
            return {"changed": operation == "disconnect", "connection": status.model_dump(), "_message": status.message}
        except (ValueError, RuntimeError) as exc:
            from agent.plugins.clickup_connection import ClickUpError
            message = str(exc) if isinstance(exc, ClickUpError) else "Check the ClickUp request fields and connection."
            raise PluginContributionActionError("CLICKUP_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("oauth.start", "Sign in with ClickUp", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel ClickUp sign-in", "write", "none"),
        ("verify", "Verify ClickUp connection", "read", "none"),
        ("disconnect", "Disconnect ClickUp", "destructive", "operation_bound"),
        ("mcp", "Apply a ClickUp change", "external_write", "operation_bound"),
    ):
        identifier = "clickup.mcp.execute" if operation == "mcp" else "clickup.connection." + operation
        schema = (ClickUpMcpOperation if operation == "mcp" else ClickUpOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="clickup", plugin_id="clickup",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="clickup.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="clickup", actions=tuple(actions))
