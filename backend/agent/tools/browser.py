"""Browser automation tools mirroring the Hermes browser toolset.

Backed by the persistent Playwright MCP browser (see
agent/mcp/playwright_tools.py). Pages are represented as accessibility trees
with ref IDs like "@e1" that browser_click/browser_type take as input. The
tool names, parameters, and semantics follow the Hermes browser docs:
navigate, snapshot, click, type, scroll, press, back, get_images, vision,
console, cdp, dialog.
"""

from langchain_core.tools import tool

from agent.mcp.playwright_tools import run_tool as playwright_run


def _run_browser(params: dict) -> str:
    return playwright_run(params)


@tool
def browser_navigate(url: str) -> str:
    """Navigate the persistent browser's current tab to a URL.

    Must be called before any other browser tool on a fresh session. Use for
    interacting with pages (clicking, filling forms, dynamic content); prefer
    web_search or web_extract for simple information retrieval.
    """

    return _run_browser({"action": "navigate", "url": url})


@tool
def browser_snapshot(full: bool = False) -> str:
    """Get a text-based snapshot of the current page's accessibility tree.

    Returns interactive elements with ref IDs like "@e1" for use with
    browser_click and browser_type. full=false (default) is a compact view of
    interactive elements; full=true returns complete page content. Snapshots
    over the per-page character budget are truncated and the complete tree is
    saved to the browser cache; call read_file on the returned path to page
    through it. Pending native dialogs appear as a pending_dialogs block.
    """

    return _run_browser({"action": "snapshot", "full": full})


@tool
def browser_click(ref: str, element: str = "") -> str:
    """Click an element identified by its ref ID (like "@e5") from browser_snapshot."""

    return _run_browser({"action": "click", "ref": ref, "element": element})


@tool
def browser_type(ref: str, text: str, element: str = "", submit: bool = False) -> str:
    """Type text into an input field identified by its ref ID from browser_snapshot.

    Clears the field first, then types the new text.
    """

    return _run_browser({"action": "type", "ref": ref, "element": element, "text": text, "submit": submit, "clear": True})


@tool
def browser_scroll(direction: str = "down") -> str:
    """Scroll the page up or down to reveal more content. direction: 'up' or 'down'."""

    return _run_browser({"action": "scroll", "direction": direction})


@tool
def browser_press(key: str) -> str:
    """Press a keyboard key. Useful for submitting forms or navigation.

    Supported keys include Enter, Tab, Escape, ArrowDown, ArrowUp, and more.
    """

    return _run_browser({"action": "press_key", "key": key})


@tool
def browser_press_key(key: str) -> str:
    """Alias of browser_press: press a keyboard key such as Enter or Escape."""

    return _run_browser({"action": "press_key", "key": key})


@tool
def browser_back() -> str:
    """Navigate back to the previous page in browser history."""

    return _run_browser({"action": "back"})


@tool
def browser_get_images() -> str:
    """List all images on the current page with their URLs and alt text.

    Useful for finding images to analyze.
    """

    return _run_browser({"action": "get_images"})


@tool
def browser_vision() -> str:
    """Take a screenshot of the current page and save it to the browser cache.

    Returns the saved file path. Use when text snapshots don't capture
    important visual information — CAPTCHAs, complex layouts, charts, or
    visual verification. Screenshots are cleaned up after 24 hours.
    """

    return _run_browser({"action": "vision"})


@tool
def browser_console(clear: bool = False, expression: str = "") -> str:
    """Get browser console output (log/warn/error messages) and uncaught JS exceptions.

    Essential for detecting silent JS errors that don't appear in the
    accessibility tree. Set clear=True to clear the console after reading so
    subsequent calls only show new messages. Pass expression to evaluate
    JavaScript instead — same shape as DevTools console; JSON-serializable
    results come back parsed.
    """

    return _run_browser({"action": "console", "clear": clear, "expression": expression})


@tool
def browser_cdp(method: str, params: str = "", target_id: str = "", frame_id: str = "") -> str:
    """Raw Chrome DevTools Protocol passthrough — the escape hatch for browser
    operations not covered by the other tools (native dialogs, iframe-scoped
    evaluation, cookie/network control).

    Only available when a CDP endpoint is configured (BROWSER_CDP_URL, e.g.
    http://127.0.0.1:9222) and reachable. Browser-level methods (Target.*,
    Browser.*, Storage.*) omit target_id. Page-level methods (Page.*,
    Runtime.*, DOM.*) require a target_id from Target.getTargets. params is a
    JSON object string. See the DevTools Protocol reference for method shapes.
    """

    return _run_browser(
        {
            "action": "cdp",
            "method": method,
            "params": params,
            "target_id": target_id,
            "frame_id": frame_id,
        }
    )


@tool
def browser_dialog(action: str = "accept", prompt_text: str = "") -> str:
    """Respond to a native JS dialog (alert / confirm / prompt / beforeunload).

    Call browser_snapshot first — a blocking dialog shows up as a
    pending_dialogs entry. Then accept or dismiss it. For prompt() dialogs,
    pass prompt_text to supply the response. Requires BROWSER_CDP_URL.
    """

    return _run_browser({"action": "dialog", "dialog_action": action, "prompt_text": prompt_text})


@tool
def browser_tabs(action: str = "list", index: str = "", url: str = "") -> str:
    """List, open, select, or close tabs in the persistent browser.

    action must be one of: list, new, select, close. For select/close, pass the
    tab index from action='list'. For new, pass url when you want the tab to
    navigate immediately.
    """

    return _run_browser({"action": "tabs", "tab_action": action, "index": index, "url": url})


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
    """Generic browser control through Playwright MCP.

    Use action='navigate' with a URL, then action='snapshot' to inspect the
    page. Use action='tabs' with tab_action='list'|'new'|'select'|'close' to
    manage tabs in the same persistent browser. Click/type actions require an
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
