"""Hermes-style web page extraction tool.

Registry-dispatched content extraction: URLs are checked for embedded
secrets and SSRF targets before any third-party backend sees them, then
dispatched to the configured extract backend (firecrawl / tavily / exa)
with head+tail truncate-and-store for pages over the char budget.
Returns a JSON string with a ``results`` list.

The legacy Firecrawl-MCP action tool (``web_extract``, action=fetch/crawl/
extract) and its ``web_extract.*`` capability records are unchanged and
separate from this tool.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

from agent.config import get_settings
from agent.tools.extract_utils import (
    DEFAULT_EXTRACT_CHAR_LIMIT,
    blocked_url_reason,
    convert_base64_images_to_links,
    normalize_extract_url,
    truncate_with_footer,
)
from agent.tools.providers import get_active_extract_provider
from agent.tools.url_safety import is_safe_url

logger = logging.getLogger(__name__)


@tool
def web_extract_pages(
    urls: list[str],
    char_limit: int | None = None,
) -> str:
    """Extract clean content from public web page URLs.

    Accepts up to 5 URLs (strings or objects with a url/href field). Returns
    per-page markdown/text content with no LLM summarization. Pages within the
    char budget (default 15000) return whole; larger pages return a head+tail
    window with a footer naming the saved full-text file and the read_file
    call to page through the omitted middle. Inline images appear as
    [IMAGE: alt] placeholders; real image URLs are kept as links. URLs with
    embedded API keys/tokens are blocked, and private/internal network
    targets (SSRF) are refused. Use after web_search or web_research finds
    URLs worth reading deeply. Never send private vault content, secrets,
    credentials, or personal files.
    """
    settings = get_settings()

    # Normalize + secret-block every URL before any network activity.
    normalized: list[str] = []
    normalized_indices: list[int] = []
    invalid: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(urls[:5]):
        raw_url = normalize_extract_url(item)
        if raw_url is None:
            invalid[index] = {
                "url": "",
                "title": "",
                "content": "",
                "error": f"Invalid URL item at index {index}: expected a URL string or an object with a 'url' or 'href' field",
            }
            continue
        blocked = blocked_url_reason(raw_url)
        if blocked:
            return json.dumps({"success": False, "error": blocked})
        normalized.append(raw_url)
        normalized_indices.append(index)

    # SSRF filter — drop private/internal targets before any backend.
    safe_urls: list[str] = []
    safe_indices: list[int] = []
    ssrf_blocked: dict[int, dict[str, Any]] = {}
    for index, url in zip(normalized_indices, normalized):
        if not is_safe_url(url):
            ssrf_blocked[index] = {
                "url": url,
                "title": "",
                "content": "",
                "error": "Blocked: URL targets a private or internal network address",
            }
        else:
            safe_urls.append(url)
            safe_indices.append(index)

    if safe_urls:
        provider = get_active_extract_provider(settings)
        if provider is None:
            return json.dumps(
                {
                    "success": False,
                    "error": (
                        "No web extract provider configured. Set WEB_EXTRACT_BACKEND "
                        "to firecrawl, tavily, or exa (and configure its API key)."
                    ),
                }
            )
        logger.info("[TOOL:web_extract_pages] extract via %s: %d URL(s)", provider.name, len(safe_urls))
        try:
            results = provider.extract(safe_urls, char_limit=char_limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[TOOL:web_extract_pages] %s extract failed: %s", provider.name, exc)
            return json.dumps(
                {"success": False, "error": f"Web extract failed via {provider.display_name}: {exc}"}
            )
    else:
        results = []

    # Reconstruct the original input order across invalid, blocked, and
    # provider-processed entries.
    if invalid or ssrf_blocked:
        safe_results = {
            index: (
                results[position]
                if position < len(results)
                else {
                    "url": safe_urls[position],
                    "title": "",
                    "content": "",
                    "error": "Extract backend returned no result for this URL",
                }
            )
            for position, index in enumerate(safe_indices)
        }
        by_index = {**safe_results, **ssrf_blocked, **invalid}
        results = [by_index[index] for index in range(len(urls[:5]))]

    # Truncate-and-store: no LLM. Convert base64 images to placeholders, then
    # return clean content within budget, or a head+tail window + footer.
    effective_limit = _clamp_char_limit(char_limit, settings.web_extract_char_limit)
    for result in results:
        if result.get("error"):
            continue
        content = result.get("raw_content") or result.get("content") or ""
        if not content:
            continue
        clean = convert_base64_images_to_links(str(content))
        model_text, truncated = truncate_with_footer(
            clean, result.get("url", ""), effective_limit, settings.web_extract_cache_dir
        )
        result["content"] = model_text
        if truncated:
            logger.info(
                "[TOOL:web_extract_pages] %s (truncated %d -> %d chars)",
                result.get("url", ""), len(clean), len(model_text),
            )

    trimmed = [
        {
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "content": r.get("content", ""),
            "error": r.get("error"),
        }
        for r in results
    ]
    if not trimmed:
        return json.dumps({"success": False, "error": "Content was inaccessible or not found"})
    return json.dumps({"results": trimmed}, indent=2, ensure_ascii=False)


def _clamp_char_limit(requested: int | None, configured: int) -> int:
    try:
        value = int(requested if requested is not None else configured)
    except (TypeError, ValueError):
        value = DEFAULT_EXTRACT_CHAR_LIMIT
    return max(2000, min(value, 500_000))
