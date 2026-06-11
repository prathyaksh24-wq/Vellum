from agent.tools.capabilities.youtube_service import YoutubeCapabilityService


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
    service = YoutubeCapabilityService(vault_root=vault, search_backend=lambda query, max_results: [])

    result = service.fetch_transcript({"video_id": "abc123XYZ09"})

    assert result["action"] == "youtube.fetch_transcript"
    assert result["transcript"] == "Arsenal transcript body."
    assert result["path"] == "Library/Youtube/channels/arsenal/videos/2026/video.md"


def test_youtube_service_registry_is_read_only(tmp_path):
    service = YoutubeCapabilityService(vault_root=tmp_path / "Vault", search_backend=lambda query, max_results: [])

    registry = service.build_registry()

    assert registry.names() == ["youtube.fetch_transcript", "youtube.search_videos"]
