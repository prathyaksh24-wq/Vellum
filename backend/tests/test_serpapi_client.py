import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from agent.tools.serpapi import SerpApiClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_serpapi_search_logs_redacted_metadata(monkeypatch, tmp_path):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        return FakeResponse(
            {
                "search_metadata": {"id": "search-123", "status": "Success"},
                "organic_results": [
                    {"title": "NBA Finals", "link": "https://www.nba.com/news/finals", "snippet": "Game update."}
                ],
            }
        )

    monkeypatch.setattr("agent.tools.serpapi.urllib.request.urlopen", fake_urlopen)
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    result = client.search({"engine": "google", "q": "nba finals", "num": 3})

    parsed = parse_qs(urlparse(seen["url"]).query)
    assert parsed["api_key"] == ["secret-token"]
    assert result["search_metadata"]["id"] == "search-123"
    log_record = json.loads((tmp_path / "serpapi.jsonl").read_text(encoding="utf-8"))
    assert log_record["search_id"] == "search-123"
    assert log_record["params"] == {"engine": "google", "q": "nba finals", "num": 3}
    assert "api_key" not in log_record["params"]
    assert "secret-token" not in json.dumps(log_record)


def test_serpapi_google_search_text_is_extractable(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.tools.serpapi.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(
            {
                "search_metadata": {"id": "search-456", "status": "Success"},
                "organic_results": [
                    {
                        "title": "Formula 1 standings",
                        "link": "https://www.formula1.com/en/results.html",
                        "snippet": "Current championship standings.",
                    }
                ],
            }
        ),
    )
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    text = client.google_search_text("formula 1 standings", num=2)

    assert "**Formula 1 standings**" in text
    assert "Current championship standings." in text
    assert "https://www.formula1.com/en/results.html" in text


def test_serpapi_google_search_prefers_ai_mode_then_light_then_normal(monkeypatch, tmp_path):
    calls = []
    responses = [
        {"search_metadata": {"id": "ai-empty", "status": "Success"}},
        {
            "search_metadata": {"id": "light-ok", "status": "Success"},
            "organic_results": [
                {
                    "title": "Portugal fixtures",
                    "link": "https://www.fifa.com/fixtures",
                    "snippet": "Portugal's next listed fixture.",
                }
            ],
        },
    ]

    def fake_urlopen(request, timeout):
        query = parse_qs(urlparse(request.full_url).query)
        calls.append(query["engine"][0])
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr("agent.tools.serpapi.urllib.request.urlopen", fake_urlopen)
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    text = client.fresh_google_search_text("Portugal vs Argentina next match", num=3)

    assert calls == ["google_ai_mode", "google_light"]
    assert "**Portugal fixtures**" in text
    assert "https://www.fifa.com/fixtures" in text


def test_serpapi_google_search_uses_normal_google_after_ai_and_light_empty(monkeypatch, tmp_path):
    calls = []
    responses = [
        {"search_metadata": {"id": "ai-empty", "status": "Success"}},
        {"search_metadata": {"id": "light-empty", "status": "Success"}},
        {
            "search_metadata": {"id": "google-ok", "status": "Success"},
            "organic_results": [
                {
                    "title": "F1 standings",
                    "link": "https://www.formula1.com/en/results.html",
                    "snippet": "Current driver standings.",
                }
            ],
        },
    ]

    def fake_urlopen(request, timeout):
        query = parse_qs(urlparse(request.full_url).query)
        calls.append(query["engine"][0])
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr("agent.tools.serpapi.urllib.request.urlopen", fake_urlopen)
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    text = client.fresh_google_search_text("formula 1 standings", num=3)

    assert calls == ["google_ai_mode", "google_light", "google"]
    assert "**F1 standings**" in text
    assert "https://www.formula1.com/en/results.html" in text


def test_serpapi_ai_mode_text_blocks_and_references_are_extractable(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.tools.serpapi.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(
            {
                "search_metadata": {"id": "ai-ok", "status": "Success"},
                "answer": "There is no Portugal vs Argentina fixture currently listed.",
                "references": [
                    {
                        "title": "FIFA Fixtures",
                        "link": "https://www.fifa.com/fixtures",
                        "snippet": "Official FIFA fixtures.",
                    }
                ],
            }
        ),
    )
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    text = client.fresh_google_search_text("Portugal vs Argentina next match", num=3)

    assert "There is no Portugal vs Argentina fixture currently listed." in text
    assert "**FIFA Fixtures**" in text
    assert "https://www.fifa.com/fixtures" in text


def test_serpapi_fresh_google_search_accumulates_sources_across_engines(monkeypatch, tmp_path):
    calls = []
    responses = [
        {
            "search_metadata": {"id": "ai-ok", "status": "Success"},
            "answer": "The next F1 race is the Austrian Grand Prix.",
            "references": [
                {
                    "title": "F1 schedule",
                    "link": "https://www.formula1.com/en/racing/2026/Austria.html",
                    "snippet": "Austria is next on the calendar.",
                }
            ],
        },
        {
            "search_metadata": {"id": "light-ok", "status": "Success"},
            "organic_results": [
                {
                    "title": "FIA calendar",
                    "link": "https://www.fia.com/events/fia-formula-one-world-championship/season-2026/calendar",
                    "snippet": "Official calendar listing.",
                },
                {
                    "title": "Autosport Austrian GP",
                    "link": "https://www.autosport.com/f1/news/austrian-gp-preview",
                    "snippet": "Austrian GP preview.",
                },
            ],
        },
    ]

    def fake_urlopen(request, timeout):
        query = parse_qs(urlparse(request.full_url).query)
        calls.append(query["engine"][0])
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr("agent.tools.serpapi.urllib.request.urlopen", fake_urlopen)
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    out = client.fresh_google_search("next f1 race", num=3, min_sources=3)

    assert calls == ["google_ai_mode", "google_light"]
    assert "Austrian Grand Prix" in out["text"]
    assert [source["url"] for source in out["sources"]] == [
        "https://www.formula1.com/en/racing/2026/Austria.html",
        "https://www.fia.com/events/fia-formula-one-world-championship/season-2026/calendar",
        "https://www.autosport.com/f1/news/austrian-gp-preview",
    ]


def test_serpapi_youtube_search_and_transcript_normalize_results(monkeypatch, tmp_path):
    responses = [
        {
            "search_metadata": {"id": "youtube-search", "status": "Success"},
            "video_results": [
                {
                    "title": "Arsenal highlights",
                    "link": "https://www.youtube.com/watch?v=abc123XYZ09",
                    "channel": {"name": "Arsenal"},
                    "published_date": "2 days ago",
                    "description": "Match highlights.",
                }
            ],
        },
        {
            "search_metadata": {"id": "youtube-transcript", "status": "Success"},
            "transcript": [
                {"text": "First line.", "start_ms": 0},
                {"text": "Second line.", "start_ms": 1000},
            ],
        },
    ]

    def fake_urlopen(request, timeout):
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr("agent.tools.serpapi.urllib.request.urlopen", fake_urlopen)
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    videos = client.youtube_search("Arsenal highlights", max_results=1)
    transcript = client.youtube_transcript("abc123XYZ09")

    assert videos == [
        {
            "videoId": "abc123XYZ09",
            "title": "Arsenal highlights",
            "url": "https://www.youtube.com/watch?v=abc123XYZ09",
            "channelName": "Arsenal",
            "publishedAt": "2 days ago",
            "description": "Match highlights.",
        }
    ]
    assert transcript == {
        "video_id": "abc123XYZ09",
        "transcript": "First line.\nSecond line.",
        "path": "",
        "segments": [{"text": "First line.", "start_ms": 0}, {"text": "Second line.", "start_ms": 1000}],
    }
