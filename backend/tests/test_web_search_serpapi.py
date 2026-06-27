import sys
import types

from agent.tools import web as web_tools


def test_web_search_prefers_serpapi_fresh_google_search_when_configured(monkeypatch, tmp_path):
    calls = {}

    class FakeSerpApiClient:
        def __init__(self, api_key, log_path):
            calls["init"] = {"api_key": api_key, "log_path": log_path}

        def fresh_google_search_text(self, query, num):
            calls["search"] = {"query": query, "num": num}
            return "**Fresh answer**\nCurrent result.\nhttps://example.com/current"

    monkeypatch.setattr(web_tools, "SerpApiClient", FakeSerpApiClient)
    monkeypatch.setattr(
        web_tools,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"serpapi_api_key": "serp-token", "serpapi_log_path": tmp_path / "serpapi.jsonl"},
        )(),
    )

    result = web_tools.web_search.invoke({"query": "what year is it"})

    assert result == "**Fresh answer**\nCurrent result.\nhttps://example.com/current"
    assert calls["init"]["api_key"] == "serp-token"
    assert calls["search"] == {"query": "what year is it", "num": 5}


def test_web_search_falls_back_when_serpapi_fails(monkeypatch):
    class FailingSerpApiClient:
        def __init__(self, api_key, log_path):
            pass

        def fresh_google_search_text(self, query, num):
            raise RuntimeError("serpapi unavailable")

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def text(self, query, max_results):
            return [{"title": "Fallback", "body": "DuckDuckGo result", "href": "https://example.com/fallback"}]

    monkeypatch.setattr(web_tools, "SerpApiClient", FailingSerpApiClient)
    monkeypatch.setattr(
        web_tools,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"serpapi_api_key": "serp-token", "serpapi_log_path": "ignored.jsonl"},
        )(),
    )
    monkeypatch.setitem(sys.modules, "duckduckgo_search", types.SimpleNamespace(DDGS=FakeDDGS))

    result = web_tools.web_search.invoke({"query": "current sports news"})

    assert "Fallback" in result
    assert "https://example.com/fallback" in result
