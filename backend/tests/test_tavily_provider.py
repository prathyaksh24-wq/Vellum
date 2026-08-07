from agent.tools.providers import tavily as tavily_module
from agent.tools.providers.tavily import TavilyProvider


def test_tavily_search_normalization(monkeypatch):
    payload = {
        "results": [
            {"title": "First", "url": "https://example.com/1", "content": "Snippet one"},
            {"title": "", "url": "https://example.com/2", "content": "Snippet two"},
            {"title": "No URL", "content": "skipped"},
        ]
    }
    monkeypatch.setattr(tavily_module, "_tavily_request", lambda endpoint, body: payload)

    response = TavilyProvider().search("hello world", limit=5)

    assert response["success"] is True
    web = response["data"]["web"]
    assert len(web) == 2
    assert web[0] == {"title": "First", "url": "https://example.com/1", "description": "Snippet one", "position": 1}
    assert web[1]["position"] == 2


def test_tavily_search_passes_limit(monkeypatch):
    captured = {}

    def fake_request(endpoint, body):
        captured["body"] = body
        return {"results": []}

    monkeypatch.setattr(tavily_module, "_tavily_request", fake_request)

    TavilyProvider().search("q", limit=12)
    assert captured["body"]["max_results"] == 12


def test_tavily_extract_normalization(monkeypatch):
    payload = {
        "results": [
            {"url": "https://example.com/a", "title": "A", "raw_content": "Full A"},
            {"url": "https://example.com/b", "content": "Full B"},
        ],
        "failed_results": [{"url": "https://example.com/c", "error": "boom"}],
        "failed_urls": ["https://example.com/d"],
    }
    monkeypatch.setattr(tavily_module, "_tavily_request", lambda endpoint, body: payload)

    documents = TavilyProvider().extract(["https://example.com/a", "https://example.com/c"])

    assert documents[0]["title"] == "A"
    assert documents[0]["content"] == "Full A"
    assert documents[1]["content"] == "Full B"
    assert documents[2]["error"] == "boom"
    assert documents[3]["error"] == "extraction failed"


def test_tavily_search_missing_key(monkeypatch):
    monkeypatch.setattr(
        tavily_module,
        "_tavily_request",
        lambda endpoint, body: (_ for _ in ()).throw(
            ValueError("TAVILY_API_KEY environment variable not set.")
        ),
    )

    response = TavilyProvider().search("q")

    assert response["success"] is False
    assert "TAVILY_API_KEY" in response["error"]
