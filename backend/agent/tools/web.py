"""Privacy-gated web search tool."""

import logging
from urllib.parse import urlparse

from langchain_core.tools import tool

from agent.config import get_settings
from agent.privacy.classifier import DataClass, classify
from agent.privacy.scrubber import PrivacyScrubber
from agent.tools.serpapi import SerpApiClient

logger = logging.getLogger(__name__)

WEB_RESULT_SEPARATOR = "\n\n---\n\n"
_WEB_ERROR_PREFIXES = (
    "Web search blocked",
    "Web search is unavailable",
    "Web search failed",
    "No web results",
)


@tool
def web_search(query: str) -> str:
    """Search the public web for current or factual information not found in the vault."""

    data_class, reason = classify(query)
    if data_class == DataClass.RED:
        return f"Web search blocked for privacy: {reason}"

    clean_query, _ = PrivacyScrubber().scrub(query)
    settings = get_settings()
    if settings.serpapi_api_key:
        try:
            result = SerpApiClient(
                api_key=settings.serpapi_api_key,
                log_path=settings.serpapi_log_path,
            ).fresh_google_search_text(clean_query, num=5)
            if result and not result.startswith("No web results"):
                return result
        except Exception as exc:
            logger.error("[TOOL:web] SerpAPI error: %s", exc)

    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "Web search is unavailable because duckduckgo-search is not installed."

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(clean_query, max_results=5))
    except Exception as exc:
        logger.error("[TOOL:web] DuckDuckGo error: %s", exc)
        return f"Web search failed: {exc}"

    if not results:
        return "No web results found."

    return WEB_RESULT_SEPARATOR.join(
        f"**{item.get('title', '')}**\n{item.get('body', '')}\n{item.get('href', '')}"
        for item in results
    )


def extract_web_sources(tool_output: str) -> list[dict]:
    """Reverse web_search's formatted output into structured source records.

    Returns a list of {title, url, snippet, domain}. web_search owns the output
    format, so this parser stays in lockstep with how that string is produced.
    """
    if not tool_output or tool_output.startswith(_WEB_ERROR_PREFIXES):
        return []
    sources: list[dict] = []
    for block in tool_output.split(WEB_RESULT_SEPARATOR):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        url = ""
        for line in reversed(lines):
            stripped = line.strip()
            if stripped.startswith(("http://", "https://")):
                url = stripped
                break
        if not url:
            continue
        title = lines[0].strip().strip("*").strip()
        snippet = " ".join(line.strip() for line in lines[1:] if line.strip() != url).strip()
        domain = urlparse(url).netloc
        if domain.startswith("www."):
            domain = domain[4:]
        sources.append({"title": title or domain, "url": url, "snippet": snippet[:300], "domain": domain})
    return sources

