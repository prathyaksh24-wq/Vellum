import json

from agent.tools import web as web_tools
from agent.tools.providers import registry
from agent.tools.providers.base import WebSearchProvider

ALL_NAMES = ("serpapi", "exa", "brave", "tavily", "ddgs", "firecrawl")


class FakeProvider(WebSearchProvider):
    def __init__(self, name, *, search=True, extract=False, available=True, fail=False, empty=False):
        self._name = name
        self._search = search
        self._extract = extract
        self._available = available
        self._fail = fail
        self._empty = empty
        self.calls = []

    @property
    def name(self):
        return self._name

    @property
    def display_name(self):
        return self._name.title()

    def is_available(self):
        return self._available

    def supports_search(self):
        return self._search

    def supports_extract(self):
        return self._extract

    def search(self, query, limit=5):
        self.calls.append({"query": query, "limit": limit})
        if self._fail:
            return {"success": False, "error": f"{self._name} unavailable"}
        if self._empty:
            return {"success": True, "data": {"web": []}}
        return {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": f"{self._name} result",
                        "url": f"https://example.com/{self._name}",
                        "description": "snippet",
                        "position": 1,
                    }
                ]
            },
        }

    def extract(self, urls, **kwargs):
        return [{"url": u, "title": "", "content": f"{self._name} content", "error": None} for u in urls]


def install_registry(monkeypatch, **providers):
    for name in ALL_NAMES:
        monkeypatch.setitem(
            registry._PROVIDERS,
            name,
            providers.get(name) or FakeProvider(name, available=False),
        )
    return providers


def test_web_search_prefers_serpapi_when_configured(monkeypatch):
    serpapi = FakeProvider("serpapi")
    exa = FakeProvider("exa", fail=True)
    install_registry(monkeypatch, serpapi=serpapi, exa=exa, brave=FakeProvider("brave", fail=True))

    result = json.loads(web_tools.web_search.invoke({"query": "what year is it"}))

    assert result["success"] is True
    assert result["data"]["web"][0]["url"] == "https://example.com/serpapi"
    assert serpapi.calls[0]["query"] == "what year is it"
    assert serpapi.calls[0]["limit"] == 5
    assert exa.calls == []


def test_web_search_uses_exa_when_serpapi_unset(monkeypatch):
    exa = FakeProvider("exa")
    install_registry(monkeypatch, exa=exa)

    result = json.loads(web_tools.web_search.invoke({"query": "neural web search"}))

    assert result["success"] is True
    assert result["data"]["web"][0]["url"] == "https://example.com/exa"
    assert exa.calls[0]["limit"] == 5


def test_web_search_falls_back_from_exa_to_brave(monkeypatch):
    exa = FakeProvider("exa", fail=True)
    brave = FakeProvider("brave")
    install_registry(monkeypatch, exa=exa, brave=brave)

    result = json.loads(web_tools.web_search.invoke({"query": "current sports news"}))

    assert result["success"] is True
    assert result["data"]["web"][0]["url"] == "https://example.com/brave"
    assert exa.calls and brave.calls


def test_web_search_falls_back_to_duckduckgo_last(monkeypatch):
    ddgs = FakeProvider("ddgs")
    install_registry(
        monkeypatch,
        exa=FakeProvider("exa", fail=True),
        brave=FakeProvider("brave", fail=True),
        ddgs=ddgs,
    )

    result = json.loads(web_tools.web_search.invoke({"query": "plain query"}))

    assert result["success"] is True
    assert result["data"]["web"][0]["url"] == "https://example.com/ddgs"


def test_web_search_skips_empty_results_and_keeps_going(monkeypatch):
    exa = FakeProvider("exa", empty=True)
    brave = FakeProvider("brave")
    install_registry(monkeypatch, exa=exa, brave=brave)

    result = json.loads(web_tools.web_search.invoke({"query": "empty then found"}))

    assert result["success"] is True
    assert result["data"]["web"][0]["url"] == "https://example.com/brave"


def test_web_search_returns_error_json_when_all_providers_fail(monkeypatch):
    install_registry(
        monkeypatch,
        serpapi=FakeProvider("serpapi", fail=True),
        exa=FakeProvider("exa", fail=True),
        brave=FakeProvider("brave", fail=True),
        ddgs=FakeProvider("ddgs", fail=True),
    )

    result = json.loads(web_tools.web_search.invoke({"query": "doomed"}))

    assert result["success"] is False
    assert "all providers" in result["error"]


def test_web_search_respects_web_search_backend_override(monkeypatch):
    serpapi = FakeProvider("serpapi")
    brave = FakeProvider("brave")
    install_registry(monkeypatch, serpapi=serpapi, brave=brave)
    monkeypatch.setattr(
        registry,
        "get_settings",
        lambda: type("Settings", (), {"web_search_backend": "brave", "web_backend": ""})(),
    )

    result = json.loads(web_tools.web_search.invoke({"query": "override me"}))

    assert result["data"]["web"][0]["url"] == "https://example.com/brave"
    assert serpapi.calls == []


def test_web_search_respects_web_backend_shared_fallback(monkeypatch):
    serpapi = FakeProvider("serpapi")
    exa = FakeProvider("exa")
    install_registry(monkeypatch, serpapi=serpapi, exa=exa)
    monkeypatch.setattr(
        registry,
        "get_settings",
        lambda: type("Settings", (), {"web_search_backend": "", "web_backend": "exa"})(),
    )

    result = json.loads(web_tools.web_search.invoke({"query": "shared backend"}))

    assert result["data"]["web"][0]["url"] == "https://example.com/exa"
    assert serpapi.calls == []


def test_web_search_returns_error_when_no_provider_configured(monkeypatch):
    install_registry(monkeypatch)

    result = json.loads(web_tools.web_search.invoke({"query": "nothing configured"}))

    assert result["success"] is False
    assert "No web search provider configured" in result["error"]


def test_web_search_clamps_limit(monkeypatch):
    serpapi = FakeProvider("serpapi")
    install_registry(monkeypatch, serpapi=serpapi)

    web_tools.web_search.invoke({"query": "limits", "limit": 200})
    assert serpapi.calls[0]["limit"] == 100

    web_tools.web_search.invoke({"query": "limits", "limit": 0})
    assert serpapi.calls[1]["limit"] == 1
