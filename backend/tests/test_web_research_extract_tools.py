from agent.tools import web_extract as web_extract_tools
from agent.tools import web_research as web_research_tools


def test_web_research_tool_routes_to_tavily_mcp(monkeypatch):
    calls = []

    def fake_run_tool(params):
        calls.append(params)
        return "research"

    monkeypatch.setattr(web_research_tools, "tavily_run", fake_run_tool)

    result = web_research_tools.web_research.invoke({"action": "search", "query": "latest ai news", "max_results": 3})

    assert result == "research"
    assert calls == [{"action": "search", "query": "latest ai news", "max_results": 3, "search_depth": ""}]


def test_web_extract_tool_routes_to_firecrawl_mcp(monkeypatch):
    calls = []

    def fake_run_tool(params):
        calls.append(params)
        return "markdown"

    monkeypatch.setattr(web_extract_tools, "firecrawl_run", fake_run_tool)

    result = web_extract_tools.web_extract.invoke({"action": "fetch", "url": "https://example.com"})

    assert result == "markdown"
    assert calls == [
        {
            "action": "fetch",
            "url": "https://example.com",
            "prompt": "",
            "limit": None,
            "schema": None,
        }
    ]
