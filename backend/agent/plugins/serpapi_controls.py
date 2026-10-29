"""SerpAPI mutations retain the existing App Action authorization and receipts."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.serpapi_connection import SerpApiMcpOperation
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.serpapi_connection import serpapi_service


def serpapi_contribution(*, service=None):
    def execute(payload, operation):
        current = service or serpapi_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "connect":
                if set(args) != {"credential_id"}:
                    raise ValueError()
                status = current.connect(args["credential_id"])
                return {"changed": True, "connection": status.model_dump(), "_message": status.message}
            elif operation == "mcp":
                from agent.plugins.serpapi_mcp import SerpApiMcpAdapter
                return SerpApiMcpAdapter(service=current).execute(SerpApiMcpOperation.model_validate(args),
                    binding=payload.get("confirmation_binding"), confirmed=payload.get("confirmed") is True)
            elif operation == "use_configured":
                if args:
                    raise ValueError()
                status = current.use_configured()
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
            from agent.plugins.serpapi_connection import SerpApiError
            message = str(exc) if isinstance(exc, SerpApiError) else "Check the SerpAPI request fields and connection."
            raise PluginContributionActionError("SERPAPI_OPERATION_FAILED", message) from None

    actions = []
    for operation, title, access, confirmation in (
        ("use_configured", "Use configured SerpAPI API credential", "write", "none"),
        ("connect", "Connect SerpAPI key", "write", "none"),

        ("verify", "Verify SerpAPI connection", "read", "none"),
        ("disconnect", "Disconnect SerpAPI", "destructive", "operation_bound"),
        ("mcp", "Apply a SerpAPI change", "external_write", "operation_bound"),
    ):
        identifier = "serpapi.mcp.execute" if operation == "mcp" else "serpapi.connection." + operation
        schema = (SerpApiMcpOperation if operation == "mcp" else None)
        arguments = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
        if operation == "connect":
            arguments = {"type":"object", "properties":{"credential_id":{"type":"string", "minLength":30, "maxLength":100}}, "required":["credential_id"], "additionalProperties":False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="serpapi", plugin_id="serpapi",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="serpapi.connection", audit_label=identifier,
            argument_schema=arguments, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="serpapi", actions=tuple(actions))
