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
