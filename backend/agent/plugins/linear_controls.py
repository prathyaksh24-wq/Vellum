"""Linear mutations use the canonical App Action review and receipt path."""
from pydantic import ValidationError

from agent.app_actions.models import AppActionDefinition
from agent.contracts.linear import PLUGIN_ID, LinearMcpOperation, LinearOAuthRequest
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.linear import LinearError, linear_service




def prepare_linear_mcp(arguments):
    from agent.plugins.linear_mcp import LinearMcpAdapter
    return LinearMcpAdapter().prepare(LinearMcpOperation.model_validate(arguments))


def linear_contribution(*, service=None):
    def execute(payload, operation):
        current = service or linear_service()
        try:
            if operation == "mcp":
                from agent.plugins.linear_mcp import LinearMcpAdapter
                return LinearMcpAdapter(service=current).execute(LinearMcpOperation.model_validate(payload.get("arguments") or {}),
                    binding=payload.get("confirmation_binding"),confirmed=payload.get("confirmed") is True)
            if operation == "oauth.start":
                from agent.plugins.linear_oauth import start_oauth
                args=LinearOAuthRequest.model_validate(payload.get("arguments") or {})
                return {"changed":True, **start_oauth(current,args.return_url).model_dump(), "_message":"Continue in Linear to approve Vellum's access."}
            if operation == "oauth.cancel":
                from agent.plugins.linear_oauth import cancel_oauth
                args=payload.get("arguments") or {}
                if set(args)!={"flow_id"} or not isinstance(args["flow_id"],str):
                    raise LinearError("Choose the current Linear sign-in flow.")
                return {"changed":True, **cancel_oauth(args["flow_id"],current),"_message":"Linear sign-in cancelled."}
            if operation != "verify" and payload.get("confirmed") is not True:
                raise LinearError("Confirm the Linear connection change first.")
            if payload.get("arguments"):
                raise LinearError("This connection action does not accept arguments.")
            status = current.verify() if operation == "verify" else current.disconnect()
            if operation == "verify":
                from agent.plugins.linear_mcp import LinearMcpAdapter
                LinearMcpAdapter(service=current).catalog()
                status=current.status()
            return {"changed": True, "connection": status.model_dump(), "_message": status.message}
        except ValidationError:
            raise PluginContributionActionError("INVALID_ACTION_ARGUMENTS", "Check the Linear operation or use its local credential form.") from None
        except LinearError as exc:
            raise PluginContributionActionError("LINEAR_OPERATION_FAILED", str(exc)) from None

    actions = []
    for operation, title, access, rule in (
        ("verify", "Verify Linear connection", "read", "none"),
        ("disconnect", "Disconnect Linear", "destructive", "operation_bound"),
        ("mcp", "Execute a Linear MCP tool", "external_write", "operation_bound"),
        ("oauth.start", "Sign in to Linear", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel Linear sign-in", "write", "none"),
    ):
        identifier = "linear.mcp.execute" if operation == "mcp" else "linear.connection." + operation
        args = LinearMcpOperation.model_json_schema() if operation == "mcp" else LinearOAuthRequest.model_json_schema() if operation=="oauth.start" else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            args={"type":"object","properties":{"flow_id":{"type":"string"}},"required":["flow_id"],"additionalProperties":False}
        actions.append(PluginActionContribution(
            definition=AppActionDefinition(id=identifier, version="1", owner=PLUGIN_ID, plugin_id=PLUGIN_ID,
                title=title, description=title + ".",
                scope="user", access_class=access, confirmation_rule=rule, executor_location="server",
                supports_undo=False, idempotent=False, ui_reference="linear.connection", audit_label=identifier,
                argument_schema=args, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner=PLUGIN_ID, actions=tuple(actions))
