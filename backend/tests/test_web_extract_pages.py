import json

from agent.tools import web_extract_pages as extract_tools
from agent.tools.providers import registry
from agent.tools.providers.base import WebSearchProvider

ALL_NAMES = ("serpapi", "exa", "brave", "tavily", "ddgs", "firecrawl")


class FakeProvider(WebSearchProvider):
    def __init__(self, name, *, search=True, extract=False, available=True, content="page content"):
        self._name = name
        self._search = search
        self._extract = extract
        self._available = available
        self.content = content
        self.extract_calls = []

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

    def extract(self, urls, **kwargs):
        self.extract_calls.append({"urls": list(urls), "kwargs": kwargs})
        return [
            {
                "url": url,
                "title": f"{self._name} title for {url}",
                "content": self.content,
                "raw_content": self.content,
                "error": None,
            }
            for url in urls
        ]


def install_extract_provider(monkeypatch, name="firecrawl", **kwargs):
    provider = FakeProvider(name, search=False, extract=True, **kwargs)
    for other in ALL_NAMES:
        if other == name:
            monkeypatch.setitem(registry._PROVIDERS, other, provider)
        else:
            monkeypatch.setitem(registry._PROVIDERS, other, FakeProvider(other, available=False))
    monkeypatch.setattr(
        extract_tools,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "web_extract_backend": "",
                "web_backend": "",
                "web_extract_char_limit": 15000,
                "web_extract_cache_dir": __import__("pathlib").Path("data/web-cache"),
            },
        )(),
    )
    return provider


def test_extract_pages_returns_content_json(monkeypatch):
    provider = install_extract_provider(monkeypatch)

    result = json.loads(extract_tools.web_extract_pages.invoke({"urls": ["https://example.com/a"]}))

    assert result["results"][0]["url"] == "https://example.com/a"
    assert result["results"][0]["content"] == "page content"
    assert provider.extract_calls[0]["urls"] == ["https://example.com/a"]


def test_extract_pages_truncates_and_stores_full_text(monkeypatch, tmp_path):
    long_content = "word " * 5000
    install_extract_provider(monkeypatch, content=long_content)
    monkeypatch.setattr(
        extract_tools,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "web_extract_backend": "",
                "web_backend": "",
                "web_extract_char_limit": 2000,
                "web_extract_cache_dir": tmp_path,
            },
        )(),
    )

    result = json.loads(extract_tools.web_extract_pages.invoke({"urls": ["https://example.com/big"]}))

    entry = result["results"][0]
    assert "[TRUNCATED]" in entry["content"]
    assert "read_file" in entry["content"]
    assert "Full text saved to:" in entry["content"]
    stored_files = list(tmp_path.iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].read_text(encoding="utf-8").startswith("word word")


def test_extract_pages_returns_whole_content_under_limit(monkeypatch):
    install_extract_provider(monkeypatch, content="short page")

    result = json.loads(extract_tools.web_extract_pages.invoke({"urls": ["https://example.com/short"]}))

    assert "[TRUNCATED]" not in result["results"][0]["content"]


def test_extract_pages_blocks_secret_urls(monkeypatch):
    install_extract_provider(monkeypatch)

    result = json.loads(
        extract_tools.web_extract_pages.invoke({"urls": ["https://example.com/watch?v=sk-abcdef1234567890xyz"]})
    )

    assert result["success"] is False
    assert "API key or token" in result["error"]


def test_extract_pages_blocks_percent_encoded_secrets(monkeypatch):
    install_extract_provider(monkeypatch)

    result = json.loads(
        extract_tools.web_extract_pages.invoke({"urls": ["https://example.com/?token=%73k-abcdef1234567890xyz"]})
    )

    assert result["success"] is False
    assert "API key or token" in result["error"]


def test_extract_pages_blocks_credential_query_param(monkeypatch):
    install_extract_provider(monkeypatch)

    result = json.loads(extract_tools.web_extract_pages.invoke({"urls": ["https://example.com/signed?session_id=abc123xyz"]}))

    assert result["success"] is False
    assert "credential-like query parameter" in result["error"]


def test_extract_pages_blocks_ssrf_targets_per_url(monkeypatch):
    provider = install_extract_provider(monkeypatch)
    monkeypatch.setattr(extract_tools, "is_safe_url", lambda url: url == "https://example.com/ok")

    result = json.loads(
        extract_tools.web_extract_pages.invoke(
            {"urls": ["https://example.com/ok", "http://127.0.0.1/internal"]}
        )
    )

    assert len(result["results"]) == 2
    assert result["results"][0]["content"] == "page content"
    assert result["results"][1]["error"] == "Blocked: URL targets a private or internal network address"
    assert provider.extract_calls[0]["urls"] == ["https://example.com/ok"]


def test_extract_pages_rejects_non_string_items_at_schema(monkeypatch):
    install_extract_provider(monkeypatch)

    try:
        extract_tools.web_extract_pages.invoke({"urls": ["https://example.com/a", 42]})
    except Exception as exc:  # noqa: BLE001
        assert "urls" in str(exc)
    else:
        raise AssertionError("expected schema validation error for non-string item")


def test_extract_pages_errors_when_no_extract_provider(monkeypatch):
    for name in ALL_NAMES:
        monkeypatch.setitem(registry._PROVIDERS, name, FakeProvider(name, available=False))
    monkeypatch.setattr(
        extract_tools,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "web_extract_backend": "",
                "web_backend": "",
                "web_extract_char_limit": 15000,
                "web_extract_cache_dir": __import__("pathlib").Path("data/web-cache"),
            },
        )(),
    )

    result = json.loads(extract_tools.web_extract_pages.invoke({"urls": ["https://example.com/a"]}))

    assert result["success"] is False
    assert "No web extract provider configured" in result["error"]


def test_extract_pages_max_five_urls(monkeypatch):
    provider = install_extract_provider(monkeypatch)

    result = json.loads(
        extract_tools.web_extract_pages.invoke({"urls": [f"https://example.com/{i}" for i in range(8)]})
    )

    assert len(result["results"]) == 5
    assert len(provider.extract_calls[0]["urls"]) == 5
