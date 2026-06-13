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
