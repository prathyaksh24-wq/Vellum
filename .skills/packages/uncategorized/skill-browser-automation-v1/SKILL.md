---
name: skill-browser-automation-v1
description: Browser automation
version: 1.0.0
metadata:
  hermes:
    category: uncategorized
    tags:
    - migrated
    - vellum
  vellum:
    trigger:
    - browser
    - playwright
    - mcp
    - navigate
    - click
    - open website
    - inspect page
    - browser automation
    - computer use
    negative_trigger: []
    confidence_threshold: 0.35
    route_to_agent: null
    routing_critical: false
x-vellum-legacy-id: skill-browser-automation-v1
x-vellum-created: '2026-05-15'
x-vellum-approved: '2026-05-15'
---

# Browser automation

## When to Use
Use when the request matches: browser, playwright, mcp, navigate, click, open website, inspect page, browser automation, computer use.

## Procedure
When the user asks Vellum to inspect or control a website, use the Hermes-style browser toolset through Playwright MCP: browser_navigate, browser_snapshot, browser_click, browser_type, browser_scroll, browser_press, browser_back, browser_get_images, browser_vision, browser_console, browser_cdp, browser_dialog.

1. Start with browser_navigate(url), then browser_snapshot so the agent can reason from the accessibility tree (interactive elements carry ref IDs like @e1).
2. Use browser_snapshot(full=true) for complete page content; snapshots over 15,000 characters are truncated with the full tree saved to data/browser-cache/web/ — call read_file on the returned path to page through it.
3. Interact via refs: browser_click(ref), browser_type(ref, text) (clears the field first), browser_scroll('up'|'down'), browser_press('Enter'), browser_back().
4. Inspect further with browser_get_images(), browser_console(clear=True) for silent JS errors, browser_console(expression=...) to evaluate JavaScript, and browser_vision() to save a screenshot (path returned; screenshots expire after 24h).
5. Native dialogs show as pending_dialogs in browser_snapshot when BROWSER_CDP_URL is configured; answer them with browser_dialog(action='accept'|'dismiss', prompt_text=...). browser_cdp(method, params, target_id) is the raw DevTools passthrough for anything else.

By default, mutating actions such as click, type, press, cdp, and dialog are blocked unless PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true. Never use browser automation for banking, purchases, password managers, account settings, destructive operations, or sending messages without an explicit user-approved control layer. Prefer snapshots over screenshots to keep context small.

## Verification
Citation style: Mention the page URL or visible page text when summarizing browser observations.
Output format: Concise prose with clear separation between observed page state and inferred next steps.
