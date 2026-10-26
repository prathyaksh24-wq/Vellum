"""Supabase mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.supabase_connection import SupabaseMcpOperation, SupabaseOAuthRequest
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.supabase_connection import supabase_service


def supabase_contribution(*, service=None):
    def execute(payload, operation):
        current = service or supabase_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "oauth.start":
                flow = current.start(SupabaseOAuthRequest.model_validate(args))
                return {"changed": True, **flow.model_dump(), "_message": flow.message}
            elif operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError()
                return current.cancel(args["flow_id"])
            elif operation == "mcp":
                from agent.plugins.supabase_mcp import SupabaseMcpAdapter
                return SupabaseMcpAdapter(service=current).execute(SupabaseMcpOperation.model_validate(args),
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
            from agent.plugins.supabase_connection import SupabaseError
            message = str(exc) if isinstance(exc, SupabaseError) else "Check the Supabase request fields and connection."
            raise PluginContributionActionError("SUPABASE_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("oauth.start", "Sign in with Supabase", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel Supabase sign-in", "write", "none"),
        ("verify", "Verify Supabase connection", "read", "none"),
        ("disconnect", "Disconnect Supabase", "destructive", "operation_bound"),
        ("mcp", "Apply a Supabase change", "external_write", "operation_bound"),
    ):
        identifier = "supabase.mcp.execute" if operation == "mcp" else "supabase.connection." + operation
        schema = (SupabaseMcpOperation if operation == "mcp" else SupabaseOAuthRequest if operation == "oauth.start" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            arguments = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="supabase", plugin_id="supabase",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="supabase.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="supabase", actions=tuple(actions))
