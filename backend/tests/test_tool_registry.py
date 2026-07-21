import pytest

from agent.tools.registry import (
    CapabilityAccess,
    CapabilityRecord,
    ToolPermissionError,
    ToolRegistry,
)


def test_tool_registry_registers_and_invokes_allowed_capability():
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="x.search_posts",
            namespace="x",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"XAgent", "VellumAgent"}),
            stream_label="Searched X",
            adapter=lambda payload: {"items": [{"text": payload["query"]}]},
        )
    )

    result = registry.invoke("x.search_posts", {"query": "arsenal"}, agent_name="XAgent")

    assert result == {"items": [{"text": "arsenal"}]}
    assert registry.get("x.search_posts").stream_label == "Searched X"


def test_tool_registry_blocks_unapproved_agent():
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="x.search_posts",
            namespace="x",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"XAgent"}),
            stream_label="Searched X",
            adapter=lambda payload: {},
        )
    )

    with pytest.raises(ToolPermissionError, match="MemoryAgent cannot use x.search_posts"):
        registry.invoke("x.search_posts", {"query": "nba"}, agent_name="MemoryAgent")


def test_tool_registry_requires_confirmation_for_external_posting():
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="x.publish_post",
            namespace="x",
            access=CapabilityAccess.EXTERNAL_WRITE,
            allowed_agents=frozenset({"XAgent"}),
            stream_label="Posted to X",
            requires_confirmation=True,
            adapter=lambda payload: {"posted": True},
        )
    )

    with pytest.raises(ToolPermissionError, match="requires explicit confirmation"):
        registry.invoke("x.publish_post", {"text": "hello"}, agent_name="XAgent")

    result = registry.invoke("x.publish_post", {"text": "hello", "confirm": True}, agent_name="XAgent")
    assert result == {"posted": True}


def test_tool_registry_requires_confirmation_for_external_write_access():
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="x.publish_post",
            namespace="x",
            access=CapabilityAccess.EXTERNAL_WRITE,
            allowed_agents=frozenset({"XAgent"}),
            stream_label="Posted to X",
            adapter=lambda payload: {"posted": True},
        )
    )

    with pytest.raises(ToolPermissionError, match="requires explicit confirmation"):
        registry.invoke("x.publish_post", {"text": "hello"}, agent_name="XAgent")

    result = registry.invoke("x.publish_post", {"text": "hello", "confirm": True}, agent_name="XAgent")
    assert result == {"posted": True}


def test_tool_registry_rejects_duplicate_capability_names():
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="x.search_posts",
            namespace="x",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"XAgent"}),
            stream_label="Searched X",
            adapter=lambda payload: {},
        )
    )

    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            CapabilityRecord(
                name="x.search_posts",
                namespace="x",
                access=CapabilityAccess.READ,
                allowed_agents=frozenset({"VellumAgent"}),
                stream_label="Searched X",
                adapter=lambda payload: {},
            )
        )


def test_tool_registry_observer_is_best_effort_and_runs_after_success():
    observed = []
    registry = ToolRegistry(observer=observed.append)
    registry.register(
        CapabilityRecord(
            name="youtube.search_videos",
            namespace="youtube",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"YoutubeAgent"}),
            stream_label="Searched YouTube",
            adapter=lambda payload: {"items": [{"video_id": payload["query"]}]},
        )
    )

    result = registry.invoke("youtube.search_videos", {"query": "video-1"}, agent_name="YoutubeAgent")

    assert result["items"][0]["video_id"] == "video-1"
    assert observed[0].name == "youtube.search_videos"
    assert observed[0].agent_name == "YoutubeAgent"


def test_tool_registry_observer_failure_does_not_break_a_successful_tool():
    def fail(_invocation):
        raise RuntimeError("observer unavailable")

    registry = ToolRegistry(observer=fail)
    registry.register(
        CapabilityRecord(
            name="x.search_posts",
            namespace="x",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"XAgent"}),
            stream_label="Searched X",
            adapter=lambda payload: {"items": [{"text": payload["query"]}]},
        )
    )

    assert registry.invoke("x.search_posts", {"query": "topic"}, agent_name="XAgent")["items"]
