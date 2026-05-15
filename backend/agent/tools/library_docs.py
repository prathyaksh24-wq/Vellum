"""Library documentation tool backed by Context7 MCP."""

from langchain_core.tools import tool

from agent.mcp.context7_tools import run_tool as context7_run


@tool
def library_docs(
    action: str,
    library: str = "",
    library_id: str = "",
    topic: str = "",
    tokens: int | None = None,
) -> str:
    """Look up current documentation for a software library via Context7 MCP.

    Two-step workflow:
      1. action="resolve", library="<free-form name>" → returns matching
         Context7 library IDs (e.g. "/vercel/next.js").
      2. action="docs", library_id="<id from step 1>", topic="<optional focus>",
         tokens=<optional cap> → returns focused documentation.

    Use only when the user asks about a specific software library or framework
    and the vault does not already cover it. Output is public OSS documentation.
    """

    return context7_run(
        {
            "action": action,
            "library": library,
            "library_id": library_id,
            "topic": topic,
            "tokens": tokens,
        }
    )
