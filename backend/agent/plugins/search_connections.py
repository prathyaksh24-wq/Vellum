"""Compatibility paths use the same user-owned grants as the plugin tools."""
import json

from agent.config import get_settings


def service_for(provider):
    if provider == 'serpapi':
        from agent.plugins.serpapi_connection import serpapi_service
        return serpapi_service()
    if provider == 'exa':
        from agent.plugins.exa_connection import exa_service
        return exa_service()
    if provider == 'tavily':
        from agent.plugins.tavily_connection import tavily_service
        return tavily_service()
    raise ValueError('Unknown search provider.')


def managed(provider):
    # A locked keyring must fail closed instead of reviving an older .env key.
    return service_for(provider).managed()


def available(provider):
    try:
        service = service_for(provider)
        if not service.enabled():
            return False
        if service.managed():
            value = service.status()
            return value.configured and not service.load().get('refresh_rejected')
        return bool(getattr(get_settings(), provider + '_api_key', ''))
    except (ValueError, RuntimeError):
        return False


def credential(provider):
    service = service_for(provider)
    if not service.enabled():
        raise ValueError(f'Enable {service.provider.name} in Plugins first.')
    if service.managed():
        value = service.require()
        if value.get('auth_type') == 'oauth':
            raise ValueError('Use the saved OAuth connection through the official MCP adapter.')
        return value['access_token']
    return getattr(get_settings(), provider + '_api_key', '')


def mcp_read(provider, tool_name, arguments):
    from agent.plugins.web_mcp_actions import WebMcpAdapter
    from agent.contracts.serpapi_connection import SerpApiMcpOperation
    # These three providers share this exact public MCP operation contract.
    result = WebMcpAdapter(service_for(provider)).read(SerpApiMcpOperation(tool_name=tool_name, arguments=arguments))
    value = json.loads(result)
    if isinstance(value, dict) and value.get('untrusted_provider_data'):
        value = value.get('data')
    return value


def search_settings():
    from agent.contracts.web_search import WebSearchChoice, WebSearchSettings
    from agent.tools.providers.registry import SEARCH_PREFERENCE, get_active_search_provider, get_provider
    settings = get_settings()
    selected = (settings.web_search_backend or settings.web_backend or 'auto').strip().lower()
    active = get_active_search_provider()
    return WebSearchSettings(selected=selected, active=active.name if active else None,
        automatic_fallback=selected == 'auto', providers=[WebSearchChoice(id=name, name=p.display_name,
            available=p.is_available()) for name in SEARCH_PREFERENCE if (p := get_provider(name)) is not None])
