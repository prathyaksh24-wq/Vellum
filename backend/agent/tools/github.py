"""GitHub tools backed by gh with a controlled MCP fallback."""

from langchain_core.tools import tool

def _connected_operation(action, arguments, *, write=False):
    """Public model tools use the plugin grant, never an unrelated global login."""
    import json
    from agent.contracts.github_connection import GitHubMcpOperation
    from agent.plugins.github_mcp import GitHubMcpAdapter
    from agent.plugins.github_connection import GitHubConnectionError
    params = {key: value for key, value in arguments.items() if value not in ("", None)}
    provider_name = {"get_file": "get_file_contents", "get_issue": "issue_read", "get_pull_request": "pull_request_read", "create_issue": "issue_write"}.get(action, action)
    if action in {"get_issue", "get_pull_request"}:
        params["method"] = "get"
    if action == "create_issue":
        params["method"] = "create"
    if "pull_number" in params:
        params["pullNumber"] = params.pop("pull_number")
    if write:
        if action == "create_repository":
            params["autoInit"] = params.pop("auto_init", True)
        else:
            params.pop("private", None)
            params.pop("auto_init", None)
        if action == "create_or_update_file" and "content" in params:
            import base64
            params["content"] = base64.b64encode(params["content"].encode()).decode()
    try:
        operation = GitHubMcpOperation(tool_name=provider_name, arguments=params)
        if write:
            from agent.tools.app_actions import app_action
            return app_action.invoke({"operation": "execute", "action_id": "github.mcp.execute", "arguments": operation.model_dump()})
        return GitHubMcpAdapter().read(operation)
    except (GitHubConnectionError, ValueError, RuntimeError):
        return json.dumps({"ok": False, "error": "Use GitHub's connected tool catalog and exact schema: github_mcp_catalog, github_mcp_describe, then github_mcp_read or github_mcp_execute. Connect GitHub in Plugins first."})


@tool
def github_read(
    action: str,
    owner: str = "",
    repo: str = "",
    query: str = "",
    path: str = "",
    ref: str = "",
    sha: str = "",
    pull_number: int | None = None,
    issue_number: int | None = None,
) -> str:
    """Read/search GitHub through gh, automatically falling back to GitHub MCP.

    Allowed actions include search_repositories, search_code, get_file,
    list_commits, get_commit, list_branches, list_releases, get_pull_request,
    list_pull_requests, get_issue, and list_issues. Write actions are blocked.
    """

    from agent.mcp.github_tools import ACTION_TO_TOOL
    if action not in ACTION_TO_TOOL:
        return "github_read accepts read operations only. Use github_mcp_execute to prepare a reviewed change."
    return _connected_operation(action,
        {
            "owner": owner,
            "repo": repo,
            "query": query,
            "path": path,
            "ref": ref,
            "sha": sha,
            "pull_number": pull_number,
            "issue_number": issue_number,
        }
    )


@tool
def github_write(
    action: str,
    owner: str = "",
    repo: str = "",
    name: str = "",
    organization: str = "",
    description: str = "",
    private: bool = True,
    auto_init: bool = True,
    branch: str = "",
    from_branch: str = "",
    path: str = "",
    content: str = "",
    message: str = "",
) -> str:
    """Prepare a reviewed GitHub change using Vellum's connected account.

    For the full provider surface use github_mcp_catalog, github_mcp_describe,
    then github_mcp_execute with the exact published arguments. This tool never
    confirms its own review or bypasses the connector's access policy.
    """

    return _connected_operation(action,
        {
            "owner": owner,
            "repo": repo,
            "name": name,
            "organization": organization,
            "description": description,
            "private": private,
            "auto_init": auto_init,
            "branch": branch,
            "from_branch": from_branch,
            "path": path,
            "content": content,
            "message": message,
        }, write=True
    )
