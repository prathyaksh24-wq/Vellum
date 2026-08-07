"""Privacy-gated multi-provider web search tool (Hermes-style registry).

Returns structured JSON: ``{"success": bool, "data": {"web": [{title, url,
description, position}]}}`` or ``{"success": False, "error": str}``.

Backend selection: ``WEB_SEARCH_BACKEND`` -> ``WEB_BACKEND`` -> availability
walk (serpapi -> exa -> brave -> tavily -> ddgs). On a transient failure the
next available provider is tried within the same call.
"""

import json
import logging
from urllib.parse import urlparse

from langchain_core.tools import tool

from agent.privacy.classifier import DataClass, classify
from agent.privacy.scrubber import PrivacyScrubber
from agent.tools.providers import available_providers, provider_chain

logger = logging.getLogger(__name__)

WEB_RESULT_SEPARATOR = "\n\n---\n\n"
PUBLIC_WEB_ENTITY_LABELS = {"PERSON", "LOCATION", "ORGANIZATION", "DATE_TIME"}
_WEB_ERROR_PREFIXES = (
    "Web search blocked",
    "Web search is unavailable",
    "Web search failed",
    "No web results",
)


@tool
def web_search(query: str, limit: int = 5) -> str:
    """Search the public web for current or factual information not found in the vault.

    Returns result metadata only (titles, URLs, descriptions) as JSON.
    Use web_extract_pages to read full content from specific URLs.
    """

    data_class, reason = classify(query)
    if data_class == DataClass.RED:
        return json.dumps(
            {"success": False, "error": f"Web search blocked for privacy: {reason}"},
            ensure_ascii=False,
        )

    clean_query = public_web_search_query(query)
    try:
        limit = min(max(int(limit), 1), 100)
    except (TypeError, ValueError):
        limit = 5

    providers = provider_chain("search")
    if not providers:
        return json.dumps(
            {
                "success": False,
                "error": (
                    "No web search provider configured. Configure a search backend "
                    "(SerpAPI, Exa, Brave, or Tavily API key) or set WEB_SEARCH_BACKEND."
                ),
            },
            ensure_ascii=False,
        )

    failed: list[str] = []
    for provider in providers:
        try:
            response = provider.search(clean_query, limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[TOOL:web] %s search failed; trying next provider: %s", provider.name, exc)
            failed.append(provider.display_name)
            continue
        if response.get("success") and response.get("data", {}).get("web"):
            return json.dumps(response, indent=2, ensure_ascii=False)
        failed.append(provider.display_name)

    return json.dumps(
        {
            "success": False,
            "error": "Web search failed via all providers" + (f": {', '.join(failed)}" if failed else "."),
        },
        ensure_ascii=False,
    )


def public_web_search_query(query: str) -> str:
    """Preserve public entities in live search while still redacting private identifiers.

    Sports, YouTube, X, and general web questions often contain names, teams,
    locations, and relative dates. Redacting those makes search useless. Keep
    those public-entity labels intact; scrub only when private-contact or
    identifier labels are mixed into the query.
    """

    raw_query = query.strip()
    scrubber = PrivacyScrubber()
    detections = scrubber.analyze(raw_query)
    if not detections:
        return raw_query
    labels = {item.label for item in detections}
    if labels <= PUBLIC_WEB_ENTITY_LABELS:
        return raw_query
    return scrubber.scrub(raw_query)[0]


def extract_web_sources(tool_output: str) -> list[dict]:
    """Reverse web_search's output into structured source records.

    Handles both the Hermes-style JSON output (``{success, data: {web:
    [{title, url, description, position}]}}``) and the legacy text-block
    format. Returns a list of {title, url, snippet, domain}.
    """
    if not tool_output or tool_output.startswith(_WEB_ERROR_PREFIXES):
        return []
    parsed_json = _try_parse_web_json(tool_output)
    if parsed_json is not None:
        return _sources_from_web_json(parsed_json)
    return _sources_from_text(tool_output)


def _try_parse_web_json(tool_output: str) -> dict | None:
    try:
        payload = json.loads(tool_output)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("web"), list):
        return payload
    return None


def _sources_from_web_json(payload: dict) -> list[dict]:
    sources: list[dict] = []
    for item in payload.get("data", {}).get("web", []):
        if not isinstance(item, dict):
            continue
        url = item.get("url", "")
        if not url:
            continue
        title = str(item.get("title", "") or "").strip()
        snippet = str(item.get("description", "") or "").strip()
        domain = urlparse(url).netloc
        if domain.startswith("www."):
            domain = domain[4:]
        sources.append({"title": title or domain, "url": url, "snippet": snippet[:300], "domain": domain})
    return sources


def _sources_from_text(tool_output: str) -> list[dict]:
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


# Keep `available_providers` importable here for introspection/health UIs.
__all__ = ["web_search", "public_web_search_query", "extract_web_sources", "available_providers"]
