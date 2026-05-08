"""Privacy-gated DuckDuckGo web search tool."""

import logging

from langchain_core.tools import tool

from agent.privacy.classifier import DataClass, classify
from agent.privacy.scrubber import PrivacyScrubber

logger = logging.getLogger(__name__)


@tool
def web_search(query: str) -> str:
    """Search the public web for current or factual information not found in the vault."""

    data_class, reason = classify(query)
    if data_class == DataClass.RED:
        return f"Web search blocked for privacy: {reason}"

    clean_query, _ = PrivacyScrubber().scrub(query)
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

    return "\n\n---\n\n".join(
        f"**{item.get('title', '')}**\n{item.get('body', '')}\n{item.get('href', '')}"
        for item in results
    )

