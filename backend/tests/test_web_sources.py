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


def test_web_search_prefers_serpapi_markdown_when_configured(monkeypatch, tmp_path):
    calls = {}

    class FakeSerpApiClient:
        def __init__(self, **kwargs):
            calls["init"] = kwargs

        def fresh_google_search(self, query, *, num=5, min_sources=3):
            calls["query"] = query
            return {
                "text": "# Search Answer\n\n- Preserved full markdown.",
                "answer_mode": "full_markdown_answer",
                "sources": [
                    {
                        "title": "Source",
                        "url": "https://example.com/source",
                        "domain": "example.com",
                    }
                ],
            }

    monkeypatch.setattr(
        web,
        "get_settings",
        lambda: SimpleNamespace(serpapi_api_key="serp", serpapi_log_path=tmp_path / "serp.jsonl"),
    )
    monkeypatch.setattr(web, "SerpApiClient", FakeSerpApiClient)

    result = web.web_search.invoke({"query": "current AI news"})

    assert calls["query"] == "current AI news"
    assert result.startswith("# Search Answer")
    assert "Preserved full markdown" in result
