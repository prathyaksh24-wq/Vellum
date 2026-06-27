"""GitHub tool backed by GitHub MCP."""

from langchain_core.tools import tool

from agent.mcp.github_tools import run_tool as github_run


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
    """Read/search GitHub through GitHub MCP.

    Allowed actions include search_repositories, search_code, get_file,
    list_commits, get_commit, list_branches, list_releases, get_pull_request,
    list_pull_requests, get_issue, and list_issues. Write actions are blocked.
    """

    return github_run(
        {
            "action": action,
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
    """Create/update GitHub resources through controlled GitHub MCP actions.

    Requires GITHUB_MCP_ALLOW_WRITES=true. Destructive actions such as
    delete_repository and delete_file also require GITHUB_MCP_ALLOW_DESTRUCTIVE=true.
    """

    return github_run(
        {
            "action": action,
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
        }
    )
