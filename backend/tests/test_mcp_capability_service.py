import pytest

from agent.tools.capabilities.mcp_service import McpCapabilityService
from agent.tools.registry import ToolPermissionError


def test_mcp_service_registers_existing_context7_and_project_tools():
    service = McpCapabilityService(runner=lambda server, params: "ok")
    registry = service.build_registry()

    assert "context7.resolve_library" in registry.names()
    assert "context7.fetch_docs" in registry.names()
    assert "context_mode.fetch_and_index" in registry.names()
    assert "github.read_issue" in registry.names()
    assert "obsidian.search_notes" in registry.names()


def test_mcp_service_invokes_context7_with_structured_result():
    calls = []

    def fake_runner(server, params):
        calls.append((server, params))
        return "Resolved /openai/openai-python"

    service = McpCapabilityService(runner=fake_runner)
    registry = service.build_registry()

    result = registry.invoke(
        "context7.resolve_library",
        {"library": "openai python"},
        agent_name="VellumAgent",
    )

    assert calls == [("context7", {"action": "resolve", "library": "openai python", "query": "openai python"})]
    assert result == {
        "action": "context7.resolve_library",
        "backend": "mcp",
        "server": "context7",
        "text": "Resolved /openai/openai-python",
    }


def test_mcp_service_gates_github_write_actions():
    service = McpCapabilityService(runner=lambda server, params: "created")
    registry = service.build_registry()

    with pytest.raises(ToolPermissionError, match="requires explicit confirmation"):
        registry.invoke(
            "github.write_issue",
            {"repo": "owner/repo", "title": "Bug", "body": "Details"},
            agent_name="CodingAgent",
        )
