"""Bounded public search completions; no browser cookies or local history sent."""
import json
from urllib.parse import urlsplit

import httpx

from agent.contracts.browser import BrowserPreferences


def search_completions(query: str, preferences: BrowserPreferences) -> tuple[list[str], str]:
    query = query.strip()
    if not preferences.suggestions_enabled:
        return [], 'off'
    if len(query) < 2 or '://' in query or query.startswith(('localhost:', '127.0.0.1:')):
        return [], 'idle'
    endpoints = {
        'google': ('https://suggestqueries.google.com/complete/search', {'client':'firefox'}),
        'brave': ('https://search.brave.com/api/suggest', {}),
        'duckduckgo': ('https://duckduckgo.com/ac/', {'type':'list'}),
        'startpage': ('https://www.startpage.com/osuggestions', {}),
    }
    if preferences.search_engine == 'searxng':
        instance = preferences.searxng_url.rstrip('/')
        parsed = urlsplit(instance)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return [], 'unavailable'
        endpoint, params = instance + '/autocompleter', {}
    else:
        endpoint, params = endpoints[preferences.search_engine]
    try:
        with httpx.Client(timeout=1.5, follow_redirects=True, max_redirects=2) as client:
            with client.stream('GET', endpoint, params={**params, 'q':query}) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 65536:
                        return [], 'unavailable'
        data = json.loads(content)
        values = data[1] if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list) else data
        if not isinstance(values, list):
            return [], 'unavailable'
        queries = []
        for value in values:
            text = value.get('phrase') if isinstance(value, dict) else value
            if isinstance(text, str) and 0 < len(text.strip()) <= 256 and text.strip() not in queries:
                queries.append(text.strip())
            if len(queries) == 6:
                break
        return queries, 'ready'
    except (httpx.HTTPError, ValueError):
        return [], 'unavailable'
