"""HubSpot mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.hubspot_connection import HubSpotMcpOperation, HubSpotOAuthRequest, HubSpotStagedReference
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.hubspot_connection import hubspot_service


def hubspot_contribution(*, service=None):
    def execute(payload, operation):
        current = service or hubspot_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "configure":
                if payload.get('confirmed') is not True:
                    raise ValueError()
                status = current.configure(HubSpotStagedReference.model_validate(args).credential_id)
            elif operation == "oauth.start":
                flow = current.start(HubSpotOAuthRequest.model_validate(args))
                return {"changed": True, **flow.model_dump(), "_message": flow.message}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.hubspot_mcp import HubSpotMcpAdapter
                return HubSpotMcpAdapter(service=current).execute(HubSpotMcpOperation.model_validate(args),
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
            from agent.plugins.hubspot_connection import HubSpotError
            message = str(exc) if isinstance(exc, HubSpotError) else "Check the HubSpot request fields and connection."
            raise PluginContributionActionError("HUBSPOT_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("configure", "Save HubSpot app setup", "external_write", "operation_bound"),
        ("oauth.start", "Sign in with HubSpot", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel HubSpot sign-in", "write", "none"),
        ("verify", "Verify HubSpot connection", "read", "none"),
        ("disconnect", "Disconnect HubSpot", "destructive", "operation_bound"),
        ("mcp", "Apply a HubSpot change", "external_write", "operation_bound"),
    ):
        identifier = "hubspot.mcp.execute" if operation == "mcp" else "hubspot.connection." + operation
        schema = (HubSpotStagedReference if operation == "configure" else HubSpotMcpOperation if operation == "mcp" else HubSpotOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="hubspot", plugin_id="hubspot",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="hubspot.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="hubspot", actions=tuple(actions))
