"""Airtable mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.airtable import AirtableMcpOperation, AirtableOAuthRequest
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.airtable import airtable_service


def airtable_contribution(*, service=None):
    def execute(payload, operation):
        current = service or airtable_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "oauth.start":
                flow = current.start(AirtableOAuthRequest.model_validate(args))
                return {"changed": True, **flow.model_dump(), "_message": flow.message}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.airtable_mcp import AirtableMcpAdapter
                return AirtableMcpAdapter(service=current).execute(AirtableMcpOperation.model_validate(args),
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
            from agent.plugins.airtable import AirtableError
            message = str(exc) if isinstance(exc, AirtableError) else "Check the Airtable request fields and connection."
            raise PluginContributionActionError("AIRTABLE_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("oauth.start", "Sign in with Airtable", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel Airtable sign-in", "write", "none"),
        ("verify", "Verify Airtable connection", "read", "none"),
        ("disconnect", "Disconnect Airtable", "destructive", "operation_bound"),
        ("mcp", "Apply an Airtable change", "external_write", "operation_bound"),
    ):
        identifier = "airtable.mcp.execute" if operation == "mcp" else "airtable.connection." + operation
        schema = (AirtableMcpOperation if operation == "mcp" else AirtableOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="airtable", plugin_id="airtable",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="airtable.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="airtable", actions=tuple(actions))
