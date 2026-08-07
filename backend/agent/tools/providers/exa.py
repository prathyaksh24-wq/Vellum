"""Exa web search + content extraction provider."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from agent.config import get_settings
from agent.tools.exa import ExaClient
from agent.tools.providers.base import WebSearchProvider
from agent.tools.providers.registry import register_provider

logger = logging.getLogger(__name__)


def _exa_snippet(item: Dict[str, Any]) -> str:
    highlights = item.get("highlights")
    if isinstance(highlights, list) and highlights:
        return " ".join(str(h) for h in highlights if h)[:700]
    text = item.get("text")
    if text:
        return str(text)[:700]
    return ""


class ExaProvider(WebSearchProvider):
    @property
    def name(self) -> str:
        return "exa"

    @property
    def display_name(self) -> str:
        return "Exa"

    def is_available(self) -> bool:
        return bool(getattr(get_settings(), "exa_api_key", ""))

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        try:
            payload = ExaClient().search(query, num_results=limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Exa search error: %s", exc)
            return {"success": False, "error": f"Exa search failed: {exc}"}

        results = payload.get("results") if isinstance(payload, dict) else []
        web: list[dict[str, Any]] = []
        for position, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not url:
                continue
            web.append(
                {
                    "title": item.get("title") or str(url),
                    "url": str(url),
                    "description": _exa_snippet(item),
                    "position": position,
                }
            )
        if not web:
            return {"success": False, "error": "No web results found."}
        return {"success": True, "data": {"web": web}}

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        max_characters = int(kwargs.get("char_limit") or 15000)
        try:
            payload = ExaClient().get_contents(urls, max_characters=max_characters)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Exa extract error: %s", exc)
            return [
                {"url": url, "title": "", "content": "", "error": f"Exa extract failed: {exc}"}
                for url in urls
            ]

        results = payload.get("results") if isinstance(payload, dict) else []
        by_url: Dict[str, Dict[str, Any]] = {}
        for item in results:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not url:
                continue
            raw = item.get("text") or item.get("content") or ""
            by_url[str(url)] = {
                "url": str(url),
                "title": item.get("title", ""),
                "content": str(raw),
                "raw_content": str(raw),
                "metadata": {"sourceURL": str(url), "title": item.get("title", "")},
            }
        documents: List[Dict[str, Any]] = []
        for url in urls:
            documents.append(
                by_url.get(url)
                or {"url": url, "title": "", "content": "", "error": "Exa returned no content for this URL"}
            )
        return documents


register_provider(ExaProvider())
