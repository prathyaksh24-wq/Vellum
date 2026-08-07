"""SerpAPI web search provider (Google results)."""

from __future__ import annotations

import logging
from typing import Any, Dict

from agent.config import get_settings
from agent.tools.providers.base import WebSearchProvider
from agent.tools.providers.registry import register_provider
from agent.tools.serpapi import SerpApiClient

logger = logging.getLogger(__name__)


class SerpApiProvider(WebSearchProvider):
    @property
    def name(self) -> str:
        return "serpapi"

    @property
    def display_name(self) -> str:
        return "SerpAPI"

    def is_available(self) -> bool:
        return bool(getattr(get_settings(), "serpapi_api_key", ""))

    def supports_search(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        try:
            client = SerpApiClient()
            result = client.fresh_google_search(query, num=limit, min_sources=3)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SerpAPI search error: %s", exc)
            return {"success": False, "error": f"SerpAPI search failed: {exc}"}

        sources = result.get("sources") if isinstance(result, dict) else []
        web: list[dict[str, Any]] = []
        for position, source in enumerate(sources, start=1):
            if not isinstance(source, dict):
                continue
            url = source.get("url", "")
            if not url:
                continue
            web.append(
                {
                    "title": source.get("title", "") or url,
                    "url": url,
                    "description": source.get("snippet", ""),
                    "position": position,
                }
            )
        if not web:
            return {"success": False, "error": "No web results found."}
        return {"success": True, "data": {"web": web}}


register_provider(SerpApiProvider())
