"""DuckDuckGo web search provider (search-only, free, last resort).

Keyless fallback used only when no paid provider is configured or the
configured chain fails. No result metadata beyond title/body/href.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from agent.tools.providers.base import WebSearchProvider
from agent.tools.providers.registry import register_provider

logger = logging.getLogger(__name__)


def _ddgs_available() -> bool:
    try:
        from duckduckgo_search import DDGS  # noqa: F401

        return True
    except ImportError:
        return False


class DuckDuckGoProvider(WebSearchProvider):
    @property
    def name(self) -> str:
        return "ddgs"

    @property
    def display_name(self) -> str:
        return "DuckDuckGo"

    def is_available(self) -> bool:
        return _ddgs_available()

    def supports_search(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        try:
            from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=limit))
        except ImportError:
            return {
                "success": False,
                "error": "Web search is unavailable because duckduckgo-search is not installed.",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("[WEB] DuckDuckGo error: %s", exc)
            return {"success": False, "error": f"DuckDuckGo search failed: {exc}"}

        web: List[Dict[str, Any]] = []
        for position, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            href = item.get("href")
            if not href:
                continue
            web.append(
                {
                    "title": item.get("title", ""),
                    "url": str(href),
                    "description": item.get("body", ""),
                    "position": position,
                }
            )
        if not web:
            return {"success": False, "error": "No web results found."}
        return {"success": True, "data": {"web": web}}


register_provider(DuckDuckGoProvider())
