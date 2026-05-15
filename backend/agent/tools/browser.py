"""Browser automation tool backed by Playwright MCP."""

from langchain_core.tools import tool

from agent.mcp.playwright_tools import run_tool as playwright_run


@tool
def browser_action(
    action: str = "snapshot",
    url: str = "",
    ref: str = "",
    element: str = "",
    text: str = "",
    key: str = "",
    value: str = "",
) -> str:
    """Control a browser through Playwright MCP.

    Use action='navigate' with a URL, then action='snapshot' to inspect the page.
    Click/type actions require an accessibility ref from a prior snapshot and
    are blocked unless PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true.
    """

    return playwright_run(
        {
            "action": action,
            "url": url,
            "ref": ref,
            "element": element,
            "text": text,
            "key": key,
            "value": value,
        }
    )
