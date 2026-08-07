from types import SimpleNamespace

from agent.tools.providers import firecrawl as firecrawl_module
from agent.tools.providers import ddgs as ddgs_module


def test_firecrawl_extract_normalization(monkeypatch):
    payload = {
        "success": True,
        "data": {
            "markdown": "# Clean markdown",
            "metadata": {"title": "Page Title"},
        },
    }
    provider = firecrawl_module.FirecrawlProvider()
    monkeypatch.setattr(provider, "_scrape", lambda url, char_limit: payload)

    documents = provider.extract(["https://example.com/page"])

    assert len(documents) == 1
    assert documents[0]["url"] == "https://example.com/page"
    assert documents[0]["title"] == "Page Title"
    assert documents[0]["content"] == "# Clean markdown"


def test_firecrawl_extract_per_url_failure(monkeypatch):
    provider = firecrawl_module.FirecrawlProvider()
    monkeypatch.setattr(
        provider,
        "_scrape",
        lambda url, char_limit: (_ for _ in ()).throw(RuntimeError("scrape failed")),
    )

    documents = provider.extract(["https://example.com/broken"])

    assert len(documents) == 1
    assert "Firecrawl extract failed" in documents[0]["error"]


def test_firecrawl_is_available(monkeypatch):
    monkeypatch.setattr(
        firecrawl_module,
        "get_settings",
        lambda: SimpleNamespace(firecrawl_api_key="fc-key"),
    )
    assert firecrawl_module.FirecrawlProvider().is_available() is True

    monkeypatch.setattr(
        firecrawl_module,
        "get_settings",
        lambda: SimpleNamespace(firecrawl_api_key=""),
    )
    assert firecrawl_module.FirecrawlProvider().is_available() is False


def test_ddgs_search_normalization(monkeypatch):
    import sys
    import types

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def text(self, query, max_results):
            return [
                {"title": "Result", "body": "Body", "href": "https://example.com/ddg"},
                {"title": "No link", "body": "skip"},
            ]

    monkeypatch.setitem(sys.modules, "duckduckgo_search", types.SimpleNamespace(DDGS=FakeDDGS))

    response = ddgs_module.DuckDuckGoProvider().search("plain query", limit=3)

    assert response["success"] is True
    assert len(response["data"]["web"]) == 1
    assert response["data"]["web"][0]["url"] == "https://example.com/ddg"


def test_ddgs_unavailable_without_package(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "duckduckgo_search", None)

    assert ddgs_module.DuckDuckGoProvider().is_available() is False
    response = ddgs_module.DuckDuckGoProvider().search("q")
    assert response["success"] is False
    assert "not installed" in response["error"]
