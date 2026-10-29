"""Swiggy mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.swiggy_connection import SwiggyMcpOperation, SwiggyOAuthRequest, SwiggySelection
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.swiggy_connection import swiggy_service


def swiggy_contribution(*, service=None):
    def execute(payload, operation):
        current = service or swiggy_service()
        try:
            args = payload.get("arguments") or {}
            if operation == 'configure':
                status = current.configure(SwiggySelection.model_validate(args))
            elif operation == "oauth.start":
                flow = current.start(SwiggyOAuthRequest.model_validate(args))
                return {"changed": True, **flow.model_dump(), "_message": flow.message}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.swiggy_mcp import SwiggyMcpAdapter
                return SwiggyMcpAdapter(service=current).execute(SwiggyMcpOperation.model_validate(args),
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
            return {"changed": operation in {"disconnect", "configure"}, "connection": status.model_dump(), "_message": status.message}
        except (ValueError, RuntimeError) as exc:
            from agent.plugins.swiggy_connection import SwiggyError
            message = str(exc) if isinstance(exc, SwiggyError) else "Check the Swiggy request fields and connection."
            raise PluginContributionActionError("SWIGGY_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ('configure', 'Choose Swiggy services', 'write', 'none'),
        ("oauth.start", "Sign in with Swiggy", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel Swiggy sign-in", "write", "none"),
        ("verify", "Verify Swiggy connection", "read", "none"),
        ("disconnect", "Disconnect Swiggy", "destructive", "operation_bound"),
        ("mcp", "Apply a Swiggy change", "external_write", "operation_bound"),
    ):
        identifier = "swiggy.mcp.execute" if operation == "mcp" else "swiggy.connection." + operation
        schema = (SwiggySelection if operation == 'configure' else SwiggyMcpOperation if operation == "mcp" else SwiggyOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="swiggy", plugin_id="swiggy",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="swiggy.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="swiggy", actions=tuple(actions))
