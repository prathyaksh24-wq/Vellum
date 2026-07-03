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


def test_serpapi_fresh_search_prioritizes_structured_fields_over_organic_results(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.tools.serpapi.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(
            {
                "search_metadata": {"id": "ai-structured", "status": "Success"},
                "ai_answer": "The next Formula 1 race is the Austrian Grand Prix, 25-28 Jun 2026.",
                "answer_box": {
                    "title": "Austrian Grand Prix",
                    "answer": "25-28 Jun 2026",
                    "link": "https://www.formula1.com/en/racing/2026/Austria.html",
                },
                "sports_results": {
                    "league": "Formula 1",
                    "games": [
                        {
                            "tournament": "Austrian Grand Prix",
                            "date": "25-28 Jun 2026",
                            "venue": "Red Bull Ring",
                            "location": "Spielberg, Austria",
                        }
                    ],
                },
                "organic_results": [
                    {
                        "title": "Monaco Grand Prix tickets",
                        "link": "https://example.com/monaco",
                        "snippet": "Monaco tickets and hospitality.",
                    }
                ],
            }
        ),
    )
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    result = client.fresh_google_search("what is the next f1 race", num=3)

    assert result["engines"] == ["google_ai_mode", "google_light", "google"]
    assert result["facts"][0] == "The next Formula 1 race is the Austrian Grand Prix, 25-28 Jun 2026."
    assert any("sports_results" in fact and "Austrian Grand Prix" in fact for fact in result["facts"])
    assert "Austrian Grand Prix" in result["text"]
    assert "Monaco" not in result["text"].split("\n\n---\n\n", 1)[0]
    assert result["sources"][0]["url"] == "https://www.formula1.com/en/racing/2026/Austria.html"


def test_serpapi_fresh_search_supplements_ai_answer_until_minimum_sources(monkeypatch, tmp_path):
    calls = []
    responses = {
        "google_ai_mode": {
            "search_metadata": {"id": "ai-answer", "status": "Success"},
            "reconstructed_markdown": "## FIFA update\n\nCanada advanced after a 1-0 win.",
            "references": [
                {
                    "title": "Google Sports data notice",
                    "link": "https://support.google.com/knowledgepanel/answer/9787176",
                    "source": "Google",
                }
            ],
        },
        "google_light": {
            "search_metadata": {"id": "light-sources", "status": "Success"},
            "organic_results": [
                {
                    "title": "World Cup fixtures",
                    "link": "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/scores-fixtures",
                    "snippet": "Official fixtures and results.",
                    "source": "FIFA",
                },
                {
                    "title": "World Cup latest",
                    "link": "https://www.bbc.com/sport/football/world-cup",
                    "snippet": "Latest match reporting.",
                    "source": "BBC",
                },
            ],
        },
    }

    def fake_urlopen(request, timeout):
        engine = parse_qs(urlparse(request.full_url).query)["engine"][0]
        calls.append(engine)
        return FakeResponse(responses[engine])

    monkeypatch.setattr("agent.tools.serpapi.urllib.request.urlopen", fake_urlopen)
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    result = client.fresh_google_search("anything new about fifa", num=5, min_sources=3)

    assert calls == ["google_ai_mode", "google_light"]
    assert result["text"].startswith("## FIFA update")
    assert [source["provider_label"] for source in result["sources"]] == ["Google", "FIFA", "BBC"]
    assert len(result["sources"]) == 3


def test_serpapi_reconstructed_markdown_is_main_source_of_truth(monkeypatch, tmp_path):
    markdown = (
        "# Ronaldo vs DR Congo\n\n"
        "Portugal drew **1-1** with DR Congo.\n\n"
        "## Match Summary\n\n"
        "- Ronaldo played 90 minutes.\n"
        "- He recorded 3 shots and 0 on target.\n\n"
        "| Player | Shots | On target |\n"
        "| --- | ---: | ---: |\n"
        "| Cristiano Ronaldo | 3 | 0 |\n"
    )
    monkeypatch.setattr(
        "agent.tools.serpapi.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(
            {
                "search_metadata": {"id": "ai-markdown", "status": "Success"},
                "reconstructed_markdown": markdown,
                "references": [
                    {
                        "title": "Portugal vs DR Congo report",
                        "link": "https://www.espn.com/soccer/report/_/gameId/760435",
                        "source": "ESPN",
                        "source_icon": "https://example.com/espn.png",
                    }
                ],
                "organic_results": [
                    {
                        "title": "Unrelated tickets",
                        "link": "https://example.com/tickets",
                        "snippet": "Ticket page.",
                    }
                ],
            }
        ),
    )
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    result = client.fresh_google_search("ronaldo performance against congo", num=3)

    assert result["answer_mode"] == "full_markdown_answer"
    assert result["facts"] == [markdown]
    assert result["text"] == markdown
    assert "| Cristiano Ronaldo | 3 | 0 |" in result["text"]
    assert "Unrelated tickets" not in result["text"]
    assert result["sources"][0]["title"] == "Portugal vs DR Congo report"
    assert result["sources"][0]["favicon_url"] == "https://example.com/espn.png"


def test_serpapi_full_answer_adds_structured_reference_table_when_answer_has_gap(monkeypatch, tmp_path):
    markdown = (
        "The next race on the official calendar is the Austrian Grand Prix.\n\n"
        "### Official 2026 F1 Calendar & Schedule\n\n"
        "The completed races and remaining schedule are detailed below:"
    )
    monkeypatch.setattr(
        "agent.tools.serpapi.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(
            {
                "search_metadata": {"id": "ai-calendar-gap", "status": "Success"},
                "reconstructed_markdown": markdown,
                "references": [
                    {
                        "title": "Formula 1 reveals calendar for 2026 season",
                        "link": "https://www.formula1.com/en/latest/article/calendar",
                        "snippet": (
                            "Table_title: 2026 F1 calendar Table_content: "
                            "| Date | Country | Venue | | --- | --- | --- | "
                            "| June 26-28 | Austria | Red Bull Ring | "
                            "| July 3-5 | Great Britain | Silverstone |"
                        ),
                    }
                ],
            }
        ),
    )
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    result = client.fresh_google_search("what is the next f1 race and show calendar details", num=3)

    assert result["answer_mode"] == "full_markdown_answer"
    assert result["facts"][0] == markdown
    assert "Formula 1 reveals calendar for 2026 season" in result["text"]
    assert "| June 26-28 | Austria | Red Bull Ring |" in result["text"]
    assert "| July 3-5 | Great Britain | Silverstone |" in result["text"]


def test_serpapi_answer_box_contents_table_is_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.tools.serpapi.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(
            {
                "search_metadata": {"id": "light-table", "status": "Success"},
                "answer_box": {
                    "title": "F1 Calendar - ESPN",
                    "link": "https://www.espn.com/f1/schedule",
                    "description": "F1 Calendar - 2026",
                    "contents": {
                        "table": [
                            ["Dates", "Race", "TV"],
                            ["Sep 24 - 26", "Qatar Airways Azerbaijan GP Baku City Circuit", "Apple TV"],
                            ["Oct 9 - 11", "Singapore Airlines Singapore GP Marina Bay Street Circuit", "Apple TV"],
                        ]
                    },
                },
                "organic_results": [
                    {
                        "title": "Old calendar",
                        "link": "https://example.com/old",
                        "snippet": "Old F1 schedule.",
                    }
                ],
            }
        ),
    )
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    result = client.fresh_google_search("f1 race calendar", num=3)

    assert result["answer_mode"] == "compact_facts"
    assert "| Dates | Race | TV |" in result["text"]
    assert "| Sep 24 - 26 | Qatar Airways Azerbaijan GP Baku City Circuit | Apple TV |" in result["text"]
    assert "Old calendar" not in result["text"].split("\n\n---\n\n", 1)[0]


def test_serpapi_text_blocks_convert_to_full_markdown(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.tools.serpapi.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(
            {
                "search_metadata": {"id": "ai-blocks", "status": "Success"},
                "text_blocks": [
                    {"type": "paragraph", "snippet": "The next F1 races from the schedule are below."},
                    {"type": "heading", "snippet": "F1 Race Calendar"},
                    {
                        "type": "table",
                        "table": [
                            ["Dates", "Race", "TV"],
                            ["Sep 24 - 26", "Qatar Airways Azerbaijan GP Baku City Circuit", "Apple TV"],
                            ["Oct 9 - 11", "Singapore Airlines Singapore GP Marina Bay Street Circuit", "Apple TV"],
                        ],
                    },
                    {
                        "type": "list",
                        "list": [
                            {"snippet": "Azerbaijan GP is the next listed event."},
                            {"snippet": "Singapore follows on Oct 9 - 11."},
                        ],
                    },
                ],
                "references": [
                    {
                        "title": "F1 Calendar - ESPN",
                        "link": "https://www.espn.com/f1/schedule",
                        "source": "ESPN",
                    }
                ],
            }
        ),
    )
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    result = client.fresh_google_search("what is the next f1 race 2026 schedule date", num=3)

    assert result["answer_mode"] == "structured_blocks"
    assert result["text"].startswith("The next F1 races from the schedule are below.")
    assert "## F1 Race Calendar" in result["text"]
    assert "| Dates | Race | TV |" in result["text"]
    assert "| Sep 24 - 26 | Qatar Airways Azerbaijan GP Baku City Circuit | Apple TV |" in result["text"]
    assert "- Azerbaijan GP is the next listed event." in result["text"]
    assert result["sources"][0]["url"] == "https://www.espn.com/f1/schedule"


def test_serpapi_video_results_preserve_titles_channels_and_links(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.tools.serpapi.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(
            {
                "search_metadata": {"id": "video-structured", "status": "Success"},
                "video_results": [
                    {
                        "title": "KSI - New Upload",
                        "link": "https://www.youtube.com/watch?v=abc123XYZ09",
                        "channel": {"name": "KSI"},
                        "published_date": "Jun 18, 2026",
                    }
                ],
                "organic_results": [
                    {
                        "title": "Zoho issue tracker",
                        "link": "https://www.zoho.com/issues",
                        "snippet": "Unrelated result.",
                    }
                ],
            }
        ),
    )
    client = SerpApiClient(api_key="secret-token", log_path=tmp_path / "serpapi.jsonl")

    result = client.fresh_google_search("what did KSI upload", num=3)

    assert result["facts"] == [
        "video_results: KSI - New Upload | channel: KSI | date: Jun 18, 2026 | link: https://www.youtube.com/watch?v=abc123XYZ09"
    ]
    assert "KSI - New Upload" in result["text"]
    assert "Zoho" not in result["text"].split("\n\n---\n\n", 1)[0]
    assert result["sources"][0]["domain"] == "youtube.com"


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
