"""Shared web extraction tool backed by Firecrawl MCP."""

from typing import Any

from langchain_core.tools import tool

from agent.mcp.firecrawl_tools import run_tool as firecrawl_run


@tool
def web_extract(
    action: str,
    url: str,
    prompt: str = "",
    limit: int | None = None,
    extraction_schema: dict[str, Any] | None = None,
) -> str:
    """Fetch, crawl, or extract public web pages with Firecrawl MCP.

    Actions:
      - fetch: url=<http(s) URL> returns page markdown.
      - crawl: url=<site URL>, limit=<optional> crawls a small site area.
      - extract: url=<page URL>, extraction_schema=<optional>, prompt=<optional> extracts structured content.

    Use this after web_search or web_research finds a URL worth reading deeply.
    Do not send private vault content, secrets, credentials, or personal files.
    """

    return firecrawl_run(
        {
            "action": action,
            "url": url,
            "prompt": prompt,
            "limit": limit,
            "schema": extraction_schema,
        }
    )
