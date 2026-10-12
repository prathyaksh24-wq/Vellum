import httpx
import pytest

from agent.contracts.browser import BrowserPreferences
from agent.mcp import browser_suggestions


def transport(monkeypatch, handler):
    client = httpx.Client
    monkeypatch.setattr(browser_suggestions.httpx, 'Client',
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.parametrize('engine,host,path', [
    ('google','suggestqueries.google.com','/complete/search'),
    ('brave','search.brave.com','/api/suggest'),
    ('duckduckgo','duckduckgo.com','/ac/'),
    ('startpage','www.startpage.com','/osuggestions'),
    ('searxng','search.example.org','/searx/autocompleter'),
])
def test_completion_uses_selected_engine_and_only_query(monkeypatch,engine,host,path):
    def respond(request):
        assert request.url.host == host and request.url.path == path
        assert request.url.params['q'] == 'anime'
        assert 'cookie' not in request.headers
        return httpx.Response(200,json=['anime',['anime news','anime movies','anime news',123]])
    transport(monkeypatch,respond)
    prefs = BrowserPreferences(search_engine=engine,searxng_url='https://search.example.org/searx')
    assert browser_suggestions.search_completions('anime',prefs) == (['anime news','anime movies'],'ready')


def test_phrase_format_is_bounded_and_invalid_items_removed(monkeypatch):
    transport(monkeypatch,lambda _: httpx.Response(200,json=[{'phrase':'anime'}, {'phrase':' '}, {'phrase':'x'*257}]
        + [{'phrase':f'anime {n}'} for n in range(10)]))
    queries,status = browser_suggestions.search_completions('anime',BrowserPreferences())
    assert status == 'ready' and len(queries) == 6 and queries[0] == 'anime'


@pytest.mark.parametrize('payload', [httpx.Response(429),httpx.Response(200,text='not json'),
    httpx.Response(200,json={'unexpected':[]}),httpx.Response(200,content=b'x'*65537)])
def test_provider_failure_keeps_search_available_without_fabricating_suggestions(monkeypatch,payload):
    transport(monkeypatch,lambda _: payload)
    assert browser_suggestions.search_completions('anime',BrowserPreferences()) == ([], 'unavailable')


@pytest.mark.parametrize('query', ['', 'a', 'https://mail.example.org/private', 'localhost:8000'])
def test_focus_on_address_or_empty_input_sends_nothing(monkeypatch,query):
    def forbidden(**_): raise AssertionError('Unexpected remote request')
    monkeypatch.setattr(browser_suggestions.httpx,'Client',forbidden)
    assert browser_suggestions.search_completions(query,BrowserPreferences()) == ([], 'idle')


def test_disabled_completions_and_unconfigured_instance_send_nothing(monkeypatch):
    def forbidden(**_): raise AssertionError('Unexpected remote request')
    monkeypatch.setattr(browser_suggestions.httpx,'Client',forbidden)
    assert browser_suggestions.search_completions('anime',BrowserPreferences(suggestions_enabled=False)) == ([], 'off')
    assert browser_suggestions.search_completions('anime',BrowserPreferences(search_engine='searxng')) == ([], 'unavailable')
