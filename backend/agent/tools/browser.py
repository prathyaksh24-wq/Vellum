"""Browser automation tool backed by Playwright MCP."""

from langchain_core.tools import tool

from agent.mcp.playwright_tools import run_tool as playwright_run


def _run_browser(params: dict) -> str:
    return playwright_run(params)


@tool
def browser_action(
    action: str = "snapshot",
    url: str = "",
    ref: str = "",
    element: str = "",
    text: str = "",
    key: str = "",
    value: str = "",
    tab_action: str = "",
    index: str = "",
) -> str:
    """Control a browser through Playwright MCP.

    Use action='navigate' with a URL, then action='snapshot' to inspect the page.
    Use action='tabs' with tab_action='list'|'new'|'select'|'close' to manage
    tabs in the same persistent browser. Click/type actions require an
    accessibility ref from a prior snapshot and are blocked unless
    PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true.
    """

    return _run_browser(
        {
            "action": action,
            "url": url,
            "ref": ref,
            "element": element,
            "text": text,
            "key": key,
            "value": value,
            "tab_action": tab_action,
            "index": index,
        }
    )


@tool
def browser_navigate(url: str) -> str:
    """Navigate the persistent Playwright browser's current tab to a URL."""

    return _run_browser({"action": "navigate", "url": url})


@tool
def browser_snapshot() -> str:
    """Inspect the current browser tab and return an accessibility snapshot with refs."""

    return _run_browser({"action": "snapshot"})


@tool
def browser_tabs(action: str = "list", index: str = "", url: str = "") -> str:
    """List, open, select, or close tabs in the persistent Playwright browser.

    action must be one of: list, new, select, close. For select/close, pass the
    tab index from action='list'. For new, pass url when you want the tab to
    navigate immediately.
    """

    return _run_browser({"action": "tabs", "tab_action": action, "index": index, "url": url})


@tool
def browser_click(ref: str, element: str = "") -> str:
    """Click an element by accessibility ref from browser_snapshot."""

    return _run_browser({"action": "click", "ref": ref, "element": element})


@tool
def browser_type(ref: str, text: str, element: str = "", submit: bool = False) -> str:
    """Type text into an element by accessibility ref from browser_snapshot."""

    return _run_browser(
        {
            "action": "type",
            "ref": ref,
            "element": element,
            "text": text,
            "submit": submit,
        }
    )


@tool
def browser_press_key(key: str) -> str:
    """Press a keyboard key in the current browser tab, such as Enter or Escape."""

    return _run_browser({"action": "press_key", "key": key})


@tool
def browser_select_option(ref: str, value: str, element: str = "") -> str:
    """Select one option in a dropdown by accessibility ref from browser_snapshot."""

    return _run_browser({"action": "select_option", "ref": ref, "element": element, "value": value})


@tool
def browser_hover(ref: str, element: str = "") -> str:
    """Hover an element by accessibility ref from browser_snapshot."""

    return _run_browser({"action": "hover", "ref": ref, "element": element})


@tool
def browser_wait(time: float = 0, text: str = "") -> str:
    """Wait for a duration or for text to appear in the current browser tab."""

    return _run_browser({"action": "wait", "time": time, "text": text})


@tool
def browser_close() -> str:
    """Close the current browser page."""

    return _run_browser({"action": "close"})
