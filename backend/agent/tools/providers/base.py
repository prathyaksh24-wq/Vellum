"""Web provider ABC — one interface for every web search/extract backend.

Port of Hermes' ``agent/web_search_provider.py`` contract. Providers
implement :class:`WebSearchProvider` and register themselves in the
:mod:`agent.tools.providers.registry`.

Response shapes (used by ``web_search`` and ``web_extract_pages`` tools):

Search::

    {"success": True, "data": {"web": [
        {"title": str, "url": str, "description": str, "position": int},
    ]}}

Extract: returns a list of per-URL documents, one entry per input URL::

    {"url", "title", "content", "raw_content", "metadata"}
    {"url", "title": "", "content": "", "error": str}   # per-URL failure

Failure (search)::

    {"success": False, "error": str}
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class WebSearchProvider(ABC):
    """A web search and/or content-extraction backend."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier used in ``WEB_*_BACKEND`` settings and logs."""

    @property
    def display_name(self) -> str:
        return self.name.title()

    def is_available(self) -> bool:
        """Return True when this provider can be used right now (key set, etc.)."""
        return False

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return False

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Run a web search.

        Returns the ``{success, data: {web: [...]}}`` shape above. Must not
        raise for ordinary failures — return ``{"success": False, "error"}``.
        """
        return {
            "success": False,
            "error": f"{self.display_name} does not support web search.",
        }

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        """Extract clean content from one or more URLs.

        Returns a list of per-URL documents (shape above), preserving the
        order of ``urls``. Per-URL failures become entries with ``error``.
        """
        return [
            {"url": url, "title": "", "content": "", "error": "extraction failed"}
            for url in urls
        ]
