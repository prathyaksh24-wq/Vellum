"""Asana mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.asana_connection import AsanaMcpOperation, AsanaOAuthRequest, AsanaStagedReference
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.asana_connection import asana_service


def asana_contribution(*, service=None):
    def execute(payload, operation):
        current = service or asana_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "configure":
                if payload.get('confirmed') is not True:
                    raise ValueError()
                status = current.configure(AsanaStagedReference.model_validate(args).credential_id)
            elif operation == "oauth.start":
                flow = current.start(AsanaOAuthRequest.model_validate(args))
                return {"changed": True, **flow.model_dump(), "_message": flow.message}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.asana_mcp import AsanaMcpAdapter
                return AsanaMcpAdapter(service=current).execute(AsanaMcpOperation.model_validate(args),
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
            from agent.plugins.asana_connection import AsanaError
            message = str(exc) if isinstance(exc, AsanaError) else "Check the Asana request fields and connection."
            raise PluginContributionActionError("ASANA_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("configure", "Save Asana app setup", "external_write", "operation_bound"),
        ("oauth.start", "Sign in with Asana", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel Asana sign-in", "write", "none"),
        ("verify", "Verify Asana connection", "read", "none"),
        ("disconnect", "Disconnect Asana", "destructive", "operation_bound"),
        ("mcp", "Apply an Asana change", "external_write", "operation_bound"),
    ):
        identifier = "asana.mcp.execute" if operation == "mcp" else "asana.connection." + operation
        schema = (AsanaStagedReference if operation == "configure" else AsanaMcpOperation if operation == "mcp" else AsanaOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="asana", plugin_id="asana",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="asana.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="asana", actions=tuple(actions))
