"""Web provider registry — resolves the active search/extract backend.

Port of Hermes' ``agent/web_search_registry.py``. Backend selection
precedence (per capability, mirroring Hermes):

1. Explicit per-capability setting: ``WEB_SEARCH_BACKEND`` / ``WEB_EXTRACT_BACKEND``.
2. Shared fallback: ``WEB_BACKEND``.
3. Availability walk over registered providers in preference order
   (search: serpapi -> exa -> brave -> tavily -> ddgs;
   extract: firecrawl -> tavily -> exa).

An explicit backend is exclusive. Only automatic selection walks the fallbacks.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from agent.config import Settings, get_settings

from agent.tools.providers.base import WebSearchProvider

logger = logging.getLogger(__name__)

SEARCH_PREFERENCE = ("serpapi", "exa", "brave", "tavily", "ddgs")
EXTRACT_PREFERENCE = ("firecrawl", "tavily", "exa")

_PROVIDERS: Dict[str, WebSearchProvider] = {}


def register_provider(provider: WebSearchProvider) -> None:
    """Register a provider instance (last writer wins)."""
    _PROVIDERS[provider.name] = provider


def get_provider(name: str) -> Optional[WebSearchProvider]:
    return _PROVIDERS.get((name or "").strip().lower())


def available_providers(capability: str) -> List[WebSearchProvider]:
    """Providers that support ``capability`` (``search``/``extract``) and are available."""
    preference = SEARCH_PREFERENCE if capability == "search" else EXTRACT_PREFERENCE
    out: List[WebSearchProvider] = []
    for name in preference:
        provider = _PROVIDERS.get(name)
        if provider is None:
            continue
        if capability == "search":
            if not (provider.is_available() and provider.supports_search()):
                continue
        else:
            if not (provider.is_available() and provider.supports_extract()):
                continue
        out.append(provider)
    return out


def _resolve_backend(settings: Settings, capability: str) -> str:
    explicit = getattr(settings, f"web_{capability}_backend", "") or ""
    if explicit:
        return '' if explicit.strip().lower() == 'auto' else explicit.strip().lower()
    shared = getattr(settings, "web_backend", "") or ""
    if shared:
        return '' if shared.strip().lower() == 'auto' else shared.strip().lower()
    return ""


def configured_backend(capability: str) -> str:
    return _resolve_backend(get_settings(), capability)


def _eligible(provider: Optional[WebSearchProvider], capability: str) -> bool:
    if provider is None:
        return False
    if not provider.is_available():
        return False
    return provider.supports_search() if capability == "search" else provider.supports_extract()


def get_active_provider(capability: str, settings: Optional[Settings] = None) -> Optional[WebSearchProvider]:
    """Resolve the active provider for a capability (search or extract)."""
    settings = settings if settings is not None else get_settings()
    backend = _resolve_backend(settings, capability)
    if backend:
        provider = get_provider(backend)
        if _eligible(provider, capability):
            return provider
        if capability == 'search':
            return None
    walk = available_providers(capability)
    if walk:
        return walk[0]
    return None


def get_active_search_provider(settings: Optional[Settings] = None) -> Optional[WebSearchProvider]:
    return get_active_provider("search", settings)


def get_active_extract_provider(settings: Optional[Settings] = None) -> Optional[WebSearchProvider]:
    return get_active_provider("extract", settings)


def provider_chain(capability: str, settings: Optional[Settings] = None) -> List[WebSearchProvider]:
    """Explicit search selection is exclusive; automatic mode permits fallback."""
    settings = settings if settings is not None else get_settings()
    active = get_active_provider(capability, settings)
    if capability == 'search' and _resolve_backend(settings, capability):
        return [active] if active is not None else []
    walk = available_providers(capability)
    if active is None:
        return walk
    if active in walk:
        return walk[walk.index(active):] + walk[: walk.index(active)]
    return [active] + walk
