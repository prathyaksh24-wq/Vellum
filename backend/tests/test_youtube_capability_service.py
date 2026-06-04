from agent.tools.capabilities.youtube_service import YoutubeCapabilityService


def test_youtube_service_returns_read_only_unsupported_result_until_backend_configured():
    service = YoutubeCapabilityService()

    result = service.search_videos({"query": "Vellum demo", "max_results": 3})

    assert result["action"] == "youtube.search_videos"
    assert result["status"] == "unsupported"
    assert "read-only YouTube backend is not configured" in result["message"]


def test_youtube_service_registers_read_only_capabilities():
    registry = YoutubeCapabilityService().build_registry()

    assert "youtube.search_videos" in registry.names()
    assert "youtube.get_transcript" in registry.names()
    assert registry.get("youtube.search_videos").stream_label == "Searched YouTube"
