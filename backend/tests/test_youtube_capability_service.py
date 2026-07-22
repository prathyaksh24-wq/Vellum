from agent.tools.capabilities.youtube_service import YoutubeCapabilityService


def test_youtube_service_prefers_serpapi_backend_over_web_fallback(tmp_path):
    calls = []

    def serpapi_search(query, max_results):
        calls.append(("serpapi", query, max_results))
        return [
            {
                "videoId": "serp123456",
                "title": "SerpAPI result",
                "url": "https://www.youtube.com/watch?v=serp123456",
            }
        ]

    def web_search(query, max_results):
        calls.append(("web", query, max_results))
        return [
            {
                "videoId": "web1234567",
                "title": "Web result",
                "url": "https://www.youtube.com/watch?v=web1234567",
            }
        ]

    service = YoutubeCapabilityService(
        vault_root=tmp_path / "Vault",
        serpapi_search_backend=serpapi_search,
        web_search_backend=web_search,
    )

    result = service.search_videos({"query": "Arsenal highlights", "max_results": 2})

    assert calls == [("serpapi", "Arsenal highlights", 2)]
    assert result["items"][0]["video_id"] == "serp123456"


def test_youtube_service_filters_non_youtube_provider_results(tmp_path):
    service = YoutubeCapabilityService(
        vault_root=tmp_path / "Vault",
        search_backend=lambda query, max_results: [
            {
                "title": "Irrelevant CRM result",
                "url": "https://www.zoho.com/issues",
                "description": "Not a YouTube video.",
            },
            {
                "title": "Creator upload",
                "url": "https://www.youtube.com/watch?v=abc123XYZ09",
                "description": "A real YouTube video.",
            },
        ],
    )

    result = service.search_videos({"query": "what did KSI upload", "max_results": 5})

    assert [item["url"] for item in result["items"]] == ["https://www.youtube.com/watch?v=abc123XYZ09"]


def test_youtube_service_falls_back_to_web_when_serpapi_empty(tmp_path):
    calls = []

    def serpapi_search(query, max_results):
        calls.append(("serpapi", query, max_results))
        return []

    def web_search(query, max_results):
        calls.append(("web", query, max_results))
        return [
            {
                "videoId": "web1234567",
                "title": "Web result",
                "url": "https://www.youtube.com/watch?v=web1234567",
            }
        ]

    service = YoutubeCapabilityService(
        vault_root=tmp_path / "Vault",
        serpapi_search_backend=serpapi_search,
        web_search_backend=web_search,
    )

    result = service.search_videos({"query": "NBA analysis", "max_results": 4})

    assert calls == [("serpapi", "NBA analysis", 4), ("web", "NBA analysis", 4)]
    assert result["items"][0]["video_id"] == "web1234567"


def test_youtube_service_filters_simulation_videos_and_ranks_official_recent_results(tmp_path):
    service = YoutubeCapabilityService(
        vault_root=tmp_path / "Vault",
        search_backend=lambda query, max_results: [
            {
                "videoId": "fake123456",
                "title": "Portugal 112-1 Argentina | Ronaldo Messi | PES Gameplay",
                "url": "https://www.youtube.com/watch?v=fake123456",
                "channelName": "Football Gaming",
                "publishedAt": "2 years ago",
                "description": "PES simulation and fantasy score.",
            },
            {
                "videoId": "fifa123456",
                "title": "Argentina v Portugal highlights",
                "url": "https://www.youtube.com/watch?v=fifa123456",
                "channelName": "FIFA",
                "publishedAt": "2 days ago",
                "description": "Official match archive highlights.",
            },
            {
                "videoId": "fan1234567",
                "title": "Argentina vs Portugal friendly highlights",
                "url": "https://www.youtube.com/watch?v=fan1234567",
                "channelName": "Football Star",
                "publishedAt": "4 years ago",
                "description": "Fan upload.",
            },
        ],
    )

    result = service.search_videos({"query": "Portugal Argentina football highlights", "max_results": 3})

    assert [item["video_id"] for item in result["items"]] == ["fifa123456", "fan1234567"]


def test_youtube_service_fetches_serpapi_transcript_before_local_cards(tmp_path):
    calls = {}

    def serpapi_transcript(video_id):
        calls["video_id"] = video_id
        return {"video_id": video_id, "transcript": "SerpAPI transcript.", "path": ""}

    service = YoutubeCapabilityService(
        vault_root=tmp_path / "Vault",
        search_backend=lambda query, max_results: [],
        serpapi_transcript_backend=serpapi_transcript,
    )

    result = service.fetch_transcript({"video_id": "abc123XYZ09"})

    assert calls == {"video_id": "abc123XYZ09"}
    assert result["transcript"] == "SerpAPI transcript."


def test_youtube_service_normalizes_search_results(tmp_path):
    service = YoutubeCapabilityService(
        vault_root=tmp_path / "Vault",
        search_backend=lambda query, max_results: [
            {
                "videoId": "abc123XYZ09",
                "title": "Arsenal title analysis",
                "url": "https://www.youtube.com/watch?v=abc123XYZ09",
                "channelName": "Football Desk",
                "publishedAt": "2026-06-01T12:00:00Z",
                "description": "Tactical breakdown.",
                "transcriptText": "Arsenal controlled the midfield and pressed high.",
            }
        ],
    )

    result = service.search_videos({"query": "Arsenal title analysis", "max_results": 3})

    assert result["action"] == "youtube.search_videos"
    assert result["items"][0] == {
        "video_id": "abc123XYZ09",
        "title": "Arsenal title analysis",
        "url": "https://www.youtube.com/watch?v=abc123XYZ09",
        "channel": "Football Desk",
        "published_at": "2026-06-01T12:00:00Z",
        "description": "Tactical breakdown.",
        "transcript": "Arsenal controlled the midfield and pressed high.",
    }


def test_youtube_service_fetches_local_transcript_card(tmp_path):
    vault = tmp_path / "Vault"
    note = vault / "Library" / "Youtube" / "channels" / "arsenal" / "videos" / "2026" / "video.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ntype: youtube_transcript\nvideo_id: \"abc123XYZ09\"\n---\n\n## Transcript\n\nArsenal transcript body.",
        encoding="utf-8",
    )
    service = YoutubeCapabilityService(
        vault_root=vault,
        search_backend=lambda query, max_results: [],
        serpapi_transcript_backend=lambda video_id: None,
    )

    result = service.fetch_transcript({"video_id": "abc123XYZ09"})

    assert result["action"] == "youtube.fetch_transcript"
    assert result["transcript"] == "Arsenal transcript body."
    assert result["path"] == "Library/Youtube/channels/arsenal/videos/2026/video.md"


def test_youtube_service_registry_is_read_only(tmp_path):
    service = YoutubeCapabilityService(
        vault_root=tmp_path / "Vault",
        search_backend=lambda query, max_results: [],
        account_backend=lambda: {"configured": True, "connected": True, "channel_title": "Pratyakksh"},
        subscriptions_backend=lambda: [
            {"channel_id": "UC-one", "title": "Channel One", "channel_url": "https://youtube.com/channel/UC-one"}
        ],
        liked_videos_backend=lambda max_results: [
            {"video_id": "liked123456", "title": "Liked video", "url": "https://youtube.com/watch?v=liked123456"}
        ],
        takeout_history_backend=lambda kind, limit: {
            "available": True,
            "kind": kind,
            "total": 2,
            "items": [{"title": "History item", "occurred_at": "2026-07-21T12:00:00+00:00"}],
        },
    )

    registry = service.build_registry()

    assert registry.names() == [
        "youtube.account",
        "youtube.fetch_transcript",
        "youtube.liked_videos",
        "youtube.search_videos",
        "youtube.subscription_feed",
        "youtube.subscriptions",
        "youtube.takeout_history",
    ]
    account = registry.invoke("youtube.account", {}, agent_name="YoutubeAgent")
    subscriptions = registry.invoke("youtube.subscriptions", {}, agent_name="YoutubeAgent")
    liked = registry.invoke("youtube.liked_videos", {"max_results": 10}, agent_name="YoutubeAgent")
    takeout = registry.invoke("youtube.takeout_history", {"kind": "watch", "limit": 10}, agent_name="YoutubeAgent")
    feed = registry.invoke("youtube.subscription_feed", {}, agent_name="YoutubeAgent")
    assert account["account"]["channel_title"] == "Pratyakksh"
    assert subscriptions["items"][0]["title"] == "Channel One"
    assert liked["items"][0]["video_id"] == "liked123456"
    assert takeout["total"] == 2
    assert feed["available"] is False
