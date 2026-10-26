"""Compatibility entry for Amazon requests through reviewed Apify Actor tools."""
import json

from langchain_core.tools import tool


@tool
def search_amazon(query: str) -> str:
    """Search Amazon for product info, prices, reviews, and product comparisons."""

    from agent.plugins.apify_connection import apify_service
    service = apify_service()
    if not service.managed():
        return json.dumps({'ok': False, 'error': 'Connect Apify in Plugins, then discover its Actor tools. Amazon searches use the same reviewed Actor connection.'})
    from agent.config import get_settings
    from agent.tools.app_actions import app_action
    data = {'search': query, 'maxItems': 5, 'scrapeProductDetails': False, 'getFullDetails': False, 'headless': True}
    published = next((item for item in service.catalog() if item['name'] == 'call-actor'), None)
    if published is None:
        return json.dumps({'ok': False, 'error': 'Search the published Apify catalog for Actor execution.'})
    schema = published['input_schema'].get('properties', {}).get('input', {})
    return app_action.invoke({'operation': 'execute', 'action_id': 'apify.mcp.execute',
        'arguments': {'tool_name': 'call-actor', 'arguments': {'actor': get_settings().apify_amazon_actor,
            'input': json.dumps(data) if schema.get('type') == 'string' else data}}})

