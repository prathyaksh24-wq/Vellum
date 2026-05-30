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
