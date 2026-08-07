"""Firecrawl content extraction provider (extract-only).

Direct REST call to the Firecrawl scrape endpoint (``POST /v1/scrape``)
with the shared ``FIRECRAWL_API_KEY``. The Firecrawl MCP surface
(``web_extract`` action tool + ``web_extract.*`` capability records) is
unchanged and separate from this provider.

Config::

    FIRECRAWL_API_KEY=...          # https://firecrawl.dev (required)
    FIRECRAWL_BASE_URL=...         # optional override of https://api.firecrawl.dev
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


class FirecrawlProvider(WebSearchProvider):
    @property
    def name(self) -> str:
        return "firecrawl"

    @property
    def display_name(self) -> str:
        return "Firecrawl"

    def is_available(self) -> bool:
        return bool(getattr(get_settings(), "firecrawl_api_key", ""))

    def supports_extract(self) -> bool:
        return True

    def _scrape(self, url: str, char_limit: int) -> Dict[str, Any]:
        settings = get_settings()
        api_key = settings.firecrawl_api_key
        if not api_key:
            raise ValueError(
                "FIRECRAWL_API_KEY environment variable not set. "
                "Get your API key at https://firecrawl.dev"
            )
        body = {"url": url, "formats": ["markdown"]}
        endpoint = f"{settings.firecrawl_base_url.rstrip('/')}/v1/scrape"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        char_limit = int(kwargs.get("char_limit") or 15000)
        documents: List[Dict[str, Any]] = []
        for url in urls:
            try:
                payload = self._scrape(url, char_limit)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Firecrawl extract error for %s: %s", url, exc)
                documents.append(
                    {"url": url, "title": "", "content": "", "error": f"Firecrawl extract failed: {exc}"}
                )
                continue
            data = payload.get("data") if isinstance(payload, dict) else {}
            markdown = data.get("markdown") or "" if isinstance(data, dict) else ""
            metadata = data.get("metadata") if isinstance(data, dict) else {}
            title = metadata.get("title", "") if isinstance(metadata, dict) else ""
            documents.append(
                {
                    "url": url,
                    "title": title,
                    "content": str(markdown),
                    "raw_content": str(markdown),
                    "metadata": {"sourceURL": url, "title": title},
                }
            )
        return documents


register_provider(FirecrawlProvider())
