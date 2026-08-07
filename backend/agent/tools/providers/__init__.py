"""Web provider registry package.

Importing this package registers all bundled providers into the registry.
"""

from agent.tools.providers.registry import (  # noqa: F401
    EXTRACT_PREFERENCE,
    SEARCH_PREFERENCE,
    available_providers,
    get_active_extract_provider,
    get_active_provider,
    get_active_search_provider,
    get_provider,
    provider_chain,
    register_provider,
)

# Provider modules register themselves at import time (last import wins).
from agent.tools.providers import brave, ddgs, exa, firecrawl, serpapi, tavily  # noqa: F401
