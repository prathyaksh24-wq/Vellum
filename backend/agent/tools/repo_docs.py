"""Repository documentation tool backed by GitMCP (gitmcp.io / idosal/git-mcp)."""

from langchain_core.tools import tool

from agent.mcp.gitmcp_tools import run_tool as gitmcp_run


@tool
def repo_docs(
    action: str,
    owner: str = "",
    repo: str = "",
    library: str = "",
    query: str = "",
    url: str = "",
    page: int | None = None,
) -> str:
    """Read docs and search code in any public GitHub repository via GitMCP.

    Actions:
      - match: library="<free-form name>" → returns likely owner/repo mappings.
      - fetch_docs: owner, repo → returns the repo's documentation (llms.txt or README-derived).
      - search_docs: owner, repo, query → semantic search over the repo's docs.
      - search_code: owner, repo, query, [page] → GitHub code search inside the repo.
      - fetch_url: url → fetch a single reference URL surfaced by the docs.

    Use when the user asks for context on a specific GitHub project that the
    vault does not cover. Output is public OSS documentation/code and is not
    scrubbed. Prefer library_docs (Context7) for well-known libraries, and
    github_read for structured PR/issue/commit data.
    """

    return gitmcp_run(
        {
            "action": action,
            "owner": owner,
            "repo": repo,
            "library": library,
            "query": query,
            "url": url,
            "page": page,
        }
    )
