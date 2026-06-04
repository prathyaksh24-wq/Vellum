from agent.tools.registry import CapabilityAccess
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService


def test_youtube_service_returns_read_only_unsupported_result_until_backend_configured():
    service = YoutubeCapabilityService()

    result = service.search_videos({"query": "Vellum demo", "max_results": 3})

    assert result["action"] == "youtube.search_videos"
    assert result["status"] == "unsupported"
    assert "read-only YouTube backend is not configured" in result["message"]


def test_youtube_service_returns_read_only_unsupported_transcript_result():
    service = YoutubeCapabilityService()

    result = service.get_transcript({"url_or_id": "abc"})

    assert result["action"] == "youtube.get_transcript"
    assert result["status"] == "unsupported"
    assert "read-only YouTube backend is not configured" in result["message"]


def test_youtube_service_registers_read_only_capabilities():
    registry = YoutubeCapabilityService().build_registry()

    assert "youtube.search_videos" in registry.names()
    assert "youtube.get_transcript" in registry.names()
    search_videos = registry.get("youtube.search_videos")
    get_transcript = registry.get("youtube.get_transcript")

    assert search_videos.access == CapabilityAccess.READ
    assert get_transcript.access == CapabilityAccess.READ
    assert search_videos.allowed_agents == frozenset({"YoutubeAgent", "ResearchAgent", "MemoryAgent", "VellumAgent"})
    assert get_transcript.allowed_agents == frozenset({"YoutubeAgent", "ResearchAgent", "MemoryAgent", "VellumAgent"})
    assert search_videos.stream_label == "Searched YouTube"


def test_youtube_service_registers_no_write_or_destructive_capabilities():
    registry = YoutubeCapabilityService().build_registry()

    for name in registry.names():
        record = registry.get(name)

        assert record.namespace == "youtube"
        assert record.access not in {
            CapabilityAccess.WRITE,
            CapabilityAccess.DESTRUCTIVE,
            CapabilityAccess.EXTERNAL_WRITE,
        }
