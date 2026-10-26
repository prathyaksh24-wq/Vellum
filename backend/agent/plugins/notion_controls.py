"""Notion mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.notion import NotionMcpOperation, NotionOAuthRequest
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.notion import notion_service


def notion_contribution(*, service=None):
    def execute(payload, operation):
        current = service or notion_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "oauth.start":
                flow = current.start(NotionOAuthRequest.model_validate(args))
                return {"changed": True, **flow.model_dump(), "_message": flow.message}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.notion_mcp import NotionMcpAdapter
                return NotionMcpAdapter(service=current).execute(NotionMcpOperation.model_validate(args),
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
            return {"changed": operation in {"disconnect"}, "connection": status.model_dump(), "_message": status.message}
        except (ValueError, RuntimeError) as exc:
            from agent.plugins.notion import NotionError
            message = str(exc) if isinstance(exc, NotionError) else "Check the Notion request fields and connection."
            raise PluginContributionActionError("NOTION_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("oauth.start", "Sign in with Notion", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel Notion sign-in", "write", "none"),
        ("verify", "Verify Notion connection", "read", "none"),
        ("disconnect", "Disconnect Notion", "destructive", "operation_bound"),
        ("mcp", "Apply an Notion change", "external_write", "operation_bound"),
    ):
        identifier = "notion.mcp.execute" if operation == "mcp" else "notion.connection." + operation
        schema = (NotionMcpOperation if operation == "mcp" else NotionOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="notion", plugin_id="notion",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="notion.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="notion", actions=tuple(actions))
