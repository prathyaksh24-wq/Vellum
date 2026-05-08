"""Amazon search tool backed by Apify MCP."""

import logging

from langchain_core.tools import tool

from agent.mcp.apify_tools import run_tool as apify_run
from agent.memory.long_term import LongTermMemory
from agent.privacy.scrubber import PrivacyScrubber

logger = logging.getLogger(__name__)


@tool
def search_amazon(query: str) -> str:
    """Search Amazon for product info, prices, reviews, and product comparisons."""

    raw = apify_run({"query": query})
    LongTermMemory().store_fact(f"Amazon search '{query}': {str(raw)[:500]}", category="amazon_search")
    clean, replacements = PrivacyScrubber().scrub(str(raw))
    logger.info("[TOOL:apify] Scrubbed %s entities from Amazon results", len(replacements))
    return clean if clean else "No Amazon results found."

