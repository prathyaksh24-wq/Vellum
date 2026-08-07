"""Tavily web search + content extraction provider.

Port of Hermes' ``plugins/web/tavily/provider.py`` using stdlib urllib
(no httpx dependency). Supports both ``/search`` and ``/extract``.

Config::

    TAVILY_API_KEY=...             # https://app.tavily.com/home (required)
    TAVILY_BASE_URL=...            # optional override of https://api.tavily.com
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
import urllib.request

from agent.config import get_settings
from agent.tools.providers.base import WebSearchProvider
from agent.tools.providers.registry import register_provider

logger = logging.getLogger(__name__)


def _tavily_request(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    settings = get_settings()
    api_key = settings.tavily_api_key
    if not api_key:
        raise ValueError(
            "TAVILY_API_KEY environment variable not set. "
            "Get your API key at https://app.tavily.com/home"
        )
    body = dict(payload)
    body["api_key"] = api_key
    url = f"{settings.tavily_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_search_results(response: Dict[str, Any]) -> Dict[str, Any]:
    web: list[dict[str, Any]] = []
    results = response.get("results") if isinstance(response, dict) else []
    for position, result in enumerate(results, start=1):
        if not isinstance(result, dict):
            continue
        url = result.get("url")
        if not url:
            continue
        web.append(
            {
                "title": result.get("title", ""),
                "url": str(url),
                "description": result.get("content", ""),
                "position": position,
            }
        )
    return {"success": True, "data": {"web": web}}


def _normalize_documents(response: Dict[str, Any], fallback_url: str = "") -> List[Dict[str, Any]]:
    documents: List[Dict[str, Any]] = []
    results = response.get("results") if isinstance(response, dict) else []
    for result in results:
        if not isinstance(result, dict):
            continue
        url = str(result.get("url") or fallback_url)
        raw = result.get("raw_content") or result.get("content") or ""
        documents.append(
            {
                "url": url,
                "title": result.get("title", ""),
                "content": str(raw),
                "raw_content": str(raw),
                "metadata": {"sourceURL": url, "title": result.get("title", "")},
            }
        )
    for fail in response.get("failed_results", []):
        if not isinstance(fail, dict):
            continue
        url = str(fail.get("url") or fallback_url)
        documents.append(
            {
                "url": url,
                "title": "",
                "content": "",
                "raw_content": "",
                "error": fail.get("error", "extraction failed"),
                "metadata": {"sourceURL": url},
            }
        )
    for fail_url in response.get("failed_urls", []):
        url = str(fail_url)
        documents.append(
            {
                "url": url,
                "title": "",
                "content": "",
                "raw_content": "",
                "error": "extraction failed",
                "metadata": {"sourceURL": url},
            }
        )
    return documents


class TavilyProvider(WebSearchProvider):
    @property
    def name(self) -> str:
        return "tavily"

    @property
    def display_name(self) -> str:
        return "Tavily"

    def is_available(self) -> bool:
        return bool(getattr(get_settings(), "tavily_api_key", ""))

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        try:
            logger.info("Tavily search: '%s' (limit=%d)", query, limit)
            raw = _tavily_request(
                "search",
                {
                    "query": query,
                    "max_results": min(limit, 20),
                    "include_raw_content": False,
                    "include_images": False,
                },
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tavily search error: %s", exc)
            return {"success": False, "error": f"Tavily search failed: {exc}"}
        return _normalize_search_results(raw)

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        try:
            logger.info("Tavily extract: %d URL(s)", len(urls))
            raw = _tavily_request("extract", {"urls": urls, "include_images": False})
        except ValueError as exc:
            return [{"url": url, "title": "", "content": "", "error": str(exc)} for url in urls]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tavily extract error: %s", exc)
            return [
                {"url": url, "title": "", "content": "", "error": f"Tavily extract failed: {exc}"}
                for url in urls
            ]
        return _normalize_documents(raw, fallback_url=urls[0] if urls else "")


register_provider(TavilyProvider())
