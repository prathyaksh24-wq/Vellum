import pytest

from agent.tools.capabilities.mcp_service import McpCapabilityService
from agent.tools.capabilities.memory_service import MemoryCapabilityService
from agent.tools.capabilities.registry import build_shared_tool_registry
from agent.tools.capabilities.x_service import XCapabilityService
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
from agent.tools.registry import ToolPermissionError


def test_shared_registry_combines_specialist_and_mcp_capabilities(tmp_path):
    registry = build_shared_tool_registry(
        vault_root=tmp_path / "Vault",
        sessions_db=tmp_path / "sessions.db",
        x_service=XCapabilityService(search_posts_backend=lambda query, max_results: [], allow_posts=True),
        youtube_service=YoutubeCapabilityService(vault_root=tmp_path / "Vault", search_backend=lambda query, max_results: []),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        mcp_service=McpCapabilityService(runner=lambda server, params: "ok"),
    )

    assert {
        "x.search_posts",
        "x.publish_post",
        "youtube.search_videos",
        "youtube.fetch_transcript",
        "memory.build_context_pack",
        "memory.review_proposals",
        "context7.resolve_library",
        "github.write_issue",
        "obsidian.search_notes",
    } <= set(registry.names())


def test_shared_registry_enforces_agent_permissions_and_confirmation(tmp_path):
    registry = build_shared_tool_registry(
        vault_root=tmp_path / "Vault",
        sessions_db=tmp_path / "sessions.db",
        x_service=XCapabilityService(
            search_posts_backend=lambda query, max_results: [],
            post_backend=lambda text: {"id": "post-1", "text": text},
            allow_posts=True,
        ),
        youtube_service=YoutubeCapabilityService(vault_root=tmp_path / "Vault", search_backend=lambda query, max_results: []),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        mcp_service=McpCapabilityService(runner=lambda server, params: "ok"),
    )

    with pytest.raises(ToolPermissionError, match="MemoryAgent cannot use x.publish_post"):
        registry.invoke("x.publish_post", {"text": "hello", "confirm": True}, agent_name="MemoryAgent")

    with pytest.raises(ToolPermissionError, match="requires explicit confirmation"):
        registry.invoke("x.publish_post", {"text": "hello"}, agent_name="XAgent")

    result = registry.invoke("x.publish_post", {"text": "hello", "confirm": True}, agent_name="XAgent")
    assert result["tweet"]["id"] == "post-1"
