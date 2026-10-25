"""GitHub connection and write controls owned by canonical App Actions."""
from agent.app_actions.models import AppActionDefinition
from agent.contracts.github_connection import GitHubConnectionRequest, GitHubMcpOperation
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.github_connection import github_service


def github_contribution(*, service=None):
    def execute(payload, operation):
        current = service or github_service()
        try:
            args = payload.get("arguments") or {}
            if operation == "oauth.start":
                return {"changed": True, **current.start(GitHubConnectionRequest.model_validate(args)).model_dump()}
            if operation == "oauth.cancel":
                if set(args) != {"flow_id"} or not isinstance(args["flow_id"], str):
                    raise ValueError("Choose the current GitHub sign-in flow.")
                return current.cancel(args["flow_id"])
            if operation == "mcp":
                from agent.plugins.github_mcp import GitHubMcpAdapter
                return GitHubMcpAdapter(service=current).execute(GitHubMcpOperation.model_validate(args),
                    binding=payload.get("confirmation_binding"), confirmed=payload.get("confirmed") is True)
            if args:
                raise ValueError("This GitHub connection control does not accept arguments.")
            if operation == "disconnect":
                if payload.get("confirmed") is not True:
                    raise ValueError("Confirm GitHub disconnection first.")
                status = current.disconnect()
            else:
                status = current.verify()
            return {"changed": operation == "disconnect", "connection": status.model_dump(), "_message": status.message}
        except (ValueError, RuntimeError):
            raise PluginContributionActionError("GITHUB_OPERATION_FAILED", "GitHub did not complete this action. Check the connection and permissions; inspect GitHub before retrying a change.") from None

    actions = []
    for operation, title, access, confirmation in (
        ("oauth.start", "Sign in with GitHub", "external_write", "oauth_consent"),
        ("oauth.cancel", "Cancel GitHub sign-in", "write", "none"),
        ("verify", "Verify GitHub connection", "read", "none"),
        ("disconnect", "Disconnect GitHub", "destructive", "operation_bound"),
        ("mcp", "Apply a GitHub change", "external_write", "operation_bound"),
    ):
        identifier = "github.mcp.execute" if operation == "mcp" else "github.connection." + operation
        schema = GitHubMcpOperation.model_json_schema() if operation == "mcp" else GitHubConnectionRequest.model_json_schema() if operation == "oauth.start" else {"type": "object", "additionalProperties": False}
        if operation == "oauth.cancel":
            schema = {"type": "object", "properties": {"flow_id": {"type": "string"}}, "required": ["flow_id"], "additionalProperties": False}
        actions.append(PluginActionContribution(definition=AppActionDefinition(id=identifier, version="1", owner="github", plugin_id="github",
            title=title, description=title + ".", scope="user", access_class=access, confirmation_rule=confirmation,
            executor_location="server", supports_undo=False, idempotent=False, ui_reference="github.connection", audit_label=identifier,
            argument_schema=schema, result_schema={"type": "object"}, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op),
            allowed_agents=frozenset({"VellumAgent", "VellumUI"}) if operation == "mcp" else frozenset({"VellumUI"})))
    return PluginContribution(owner="github", actions=tuple(actions))
