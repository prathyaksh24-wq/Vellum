"""Brave Search web search provider (search-only)."""

from __future__ import annotations

import logging
from typing import Any, Dict

from agent.config import get_settings
from agent.tools.brave import BraveClient
from agent.tools.providers.base import WebSearchProvider
from agent.tools.providers.registry import register_provider

logger = logging.getLogger(__name__)


class BraveProvider(WebSearchProvider):
    @property
    def name(self) -> str:
        return "brave"

    @property
    def display_name(self) -> str:
        return "Brave"

    def is_available(self) -> bool:
        return bool(getattr(get_settings(), "brave_api_key", ""))

    def supports_search(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        try:
            payload = BraveClient().search(query, count=limit, extra_snippets=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Brave search error: %s", exc)
            return {"success": False, "error": f"Brave search failed: {exc}"}

        web_data = payload.get("web") if isinstance(payload, dict) else {}
        results = web_data.get("results") if isinstance(web_data, dict) else []
        web: list[dict[str, Any]] = []
        for position, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not url:
                continue
            description = str(item.get("description") or "")
            extra = item.get("extra_snippets")
            if not description and isinstance(extra, list) and extra:
                description = " ".join(str(s) for s in extra if s)[:700]
            web.append(
                {
                    "title": item.get("title") or str(url),
                    "url": str(url),
                    "description": description,
                    "position": position,
                }
            )
        if not web:
            return {"success": False, "error": "No web results found."}
        return {"success": True, "data": {"web": web}}


register_provider(BraveProvider())
