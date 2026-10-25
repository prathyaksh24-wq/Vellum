"""Slack mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.slack import SlackAppRegistration, SlackMcpOperation, SlackOAuthRequest
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.slack import slack_service


def slack_contribution(*, service=None):
    def execute(payload, operation):
        current = service or slack_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "configure":
                status = current.configure(SlackAppRegistration.model_validate(args))
            elif operation == "oauth.start":
                return {"changed": True, **current.start(SlackOAuthRequest.model_validate(args)).model_dump()}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.slack_mcp import SlackMcpAdapter
                return SlackMcpAdapter(service=current).execute(SlackMcpOperation.model_validate(args),
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
            return {"changed": operation in {"configure", "disconnect"}, "connection": status.model_dump(), "_message": status.message}
        except (ValueError, RuntimeError) as exc:
            from agent.plugins.slack import SlackError
            message = str(exc) if isinstance(exc, SlackError) else "Check the Slack request fields and connection."
            raise PluginContributionActionError("SLACK_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("configure", "Save Slack app registration", "write", "none"),
        ("oauth.start", "Sign in with Slack", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel Slack sign-in", "write", "none"),
        ("verify", "Verify Slack connection", "read", "none"),
        ("disconnect", "Disconnect Slack", "destructive", "operation_bound"),
        ("mcp", "Apply a Slack change", "external_write", "operation_bound"),
    ):
        identifier = "slack.mcp.execute" if operation == "mcp" else "slack.connection." + operation
        schema = (SlackMcpOperation if operation == "mcp" else SlackAppRegistration if operation == "configure" else SlackOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="slack", plugin_id="slack",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="slack.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="slack", actions=tuple(actions))
