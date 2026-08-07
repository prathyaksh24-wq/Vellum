from types import SimpleNamespace

from agent.tools import web
from agent.tools.web import extract_web_sources

SAMPLE = (
    "**Arsenal beat PSG 2-1**\n"
    "Arsenal edged PSG in a thriller at the Puskas Arena.\n"
    "https://www.uefa.com/championsleague/news/123\n"
    "\n---\n\n"
    "**Match report: Antonelli wins**\n"
    "Kimi Antonelli took his fourth straight win.\n"
    "https://www.skysports.com/f1/report/abc\n"
    "\n---\n\n"
    "**No URL block**\n"
    "just text, no link here"
)


def test_extract_web_sources_parses_blocks_with_urls():
    sources = extract_web_sources(SAMPLE)

    assert len(sources) == 2  # the block without a URL is skipped
    assert sources[0]["title"] == "Arsenal beat PSG 2-1"
    assert sources[0]["url"] == "https://www.uefa.com/championsleague/news/123"
    assert sources[0]["domain"] == "uefa.com"  # www. stripped
    assert "Arsenal edged PSG" in sources[0]["snippet"]
    assert sources[1]["domain"] == "skysports.com"
    assert "Antonelli" in sources[1]["snippet"]


def test_extract_web_sources_handles_empty_and_error_outputs():
    assert extract_web_sources("") == []
    assert extract_web_sources("No web results found.") == []
    assert extract_web_sources("Web search failed: boom") == []
    assert extract_web_sources("Web search blocked for privacy: x") == []


def test_extract_web_sources_truncates_long_snippets():
    block = "**T**\n" + ("word " * 200) + "\nhttps://example.com/x"
    sources = extract_web_sources(block)

    assert len(sources) == 1
    assert sources[0]["domain"] == "example.com"
    assert len(sources[0]["snippet"]) <= 300


def test_extract_web_sources_parses_hermes_json_shape():
    import json

    payload = {
        "success": True,
        "data": {
            "web": [
                {
                    "title": "Arsenal beat PSG 2-1",
                    "url": "https://www.uefa.com/championsleague/news/123",
                    "description": "Arsenal edged PSG in a thriller.",
                    "position": 1,
                },
                {
                    "title": "Match report: Antonelli wins",
                    "url": "https://www.skysports.com/f1/report/abc",
                    "description": "Kimi Antonelli took his fourth straight win.",
                    "position": 2,
                },
            ]
        },
    }
    sources = extract_web_sources(json.dumps(payload))

    assert len(sources) == 2
    assert sources[0]["title"] == "Arsenal beat PSG 2-1"
    assert sources[0]["url"] == "https://www.uefa.com/championsleague/news/123"
    assert sources[0]["domain"] == "uefa.com"
    assert "thriller" in sources[0]["snippet"]
    assert sources[1]["domain"] == "skysports.com"


def test_extract_web_sources_ignores_failed_json_payloads():
    import json

    assert extract_web_sources(json.dumps({"success": False, "error": "Web search failed: boom"})) == []
    assert extract_web_sources('{"success": true, "data": {"web": []}}') == []
    assert extract_web_sources('{"unexpected": true}') == []


def test_extract_web_sources_json_truncates_long_snippets():
    import json

    payload = {
        "success": True,
        "data": {
            "web": [
                {
                    "title": "T",
                    "url": "https://example.com/x",
                    "description": "word " * 200,
                    "position": 1,
                }
            ]
        },
    }
    sources = extract_web_sources(json.dumps(payload))

    assert len(sources) == 1
    assert len(sources[0]["snippet"]) <= 300


def test_extract_web_sources_parses_real_tool_output_back_and_forth(monkeypatch):
    """End-to-end: web_search JSON output must round-trip through extract_web_sources."""
    from agent.tools.providers import registry
    from agent.tools.providers.base import WebSearchProvider

    class FakeProvider(WebSearchProvider):
        @property
        def name(self):
            return "serpapi"

        @property
        def display_name(self):
            return "SerpAPI"

        def is_available(self):
            return True

        def supports_search(self):
            return True

        def search(self, query, limit=5):
            return {
                "success": True,
                "data": {
                    "web": [
                        {
                            "title": "Current AI news",
                            "url": "https://example.com/ai",
                            "description": "Fresh coverage.",
                            "position": 1,
                        }
                    ]
                },
            }

    for name in ("serpapi", "exa", "brave", "tavily", "ddgs", "firecrawl"):
        monkeypatch.setitem(registry._PROVIDERS, name, FakeProvider() if name == "serpapi" else SimpleNamespace(is_available=lambda: False, supports_search=lambda: False, supports_extract=lambda: False))

    output = web.web_search.invoke({"query": "current AI news"})

    sources = extract_web_sources(output)
    assert len(sources) == 1
    assert sources[0]["title"] == "Current AI news"
    assert sources[0]["url"] == "https://example.com/ai"
