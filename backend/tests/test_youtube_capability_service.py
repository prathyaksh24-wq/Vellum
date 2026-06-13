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
    service = YoutubeCapabilityService(vault_root=tmp_path / "Vault", search_backend=lambda query, max_results: [])

    registry = service.build_registry()

    assert registry.names() == ["youtube.fetch_transcript", "youtube.search_videos"]
