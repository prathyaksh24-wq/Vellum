"""Shared live web research tool backed by Tavily MCP."""

from langchain_core.tools import tool

from agent.mcp.tavily_tools import run_tool as tavily_run


@tool
def web_research(
    action: str,
    query: str,
    max_results: int | None = None,
    search_depth: str = "",
) -> str:
    """Search or answer with Tavily MCP for public, current web research.

    Actions:
      - search: query=<public query>, max_results=<optional>
      - answer: query=<public question>; asks Tavily to include a direct answer.

    Use this for source-backed research when normal web_search is insufficient.
    Do not send private vault content, secrets, credentials, or personal files.
    """

    return tavily_run(
        {
            "action": action,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
        }
    )
