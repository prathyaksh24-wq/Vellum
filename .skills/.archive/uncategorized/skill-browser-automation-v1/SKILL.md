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
When the user asks Vellum to inspect or control a website, use browser_action through Playwright MCP. Start with action='navigate' and action='snapshot' so the agent can reason from the accessibility tree. By default, mutating actions such as click, type, press_key, select_option, and hover are blocked unless PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true. Never use browser automation for banking, purchases, password managers, account settings, destructive operations, or sending messages without an explicit user-approved control layer. Prefer snapshots over screenshots to keep context small.

## Verification
Citation style: Mention the page URL or visible page text when summarizing browser observations.
Output format: Concise prose with clear separation between observed page state and inferred next steps.
