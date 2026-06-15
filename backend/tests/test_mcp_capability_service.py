import asyncio
from types import SimpleNamespace

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
    assert "web_research.search" in registry.names()
    assert "web_research.answer" in registry.names()
    assert "web_extract.fetch" in registry.names()
    assert "web_extract.crawl" in registry.names()
    assert "web_extract.extract" in registry.names()


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


def test_mcp_service_invokes_context_mode_fetch_and_index_with_action():
    calls = []

    def fake_runner(server, params):
        calls.append((server, params))
        return "indexed"

    service = McpCapabilityService(runner=fake_runner)
    registry = service.build_registry()

    result = registry.invoke(
        "context_mode.fetch_and_index",
        {"url": "https://example.com"},
        agent_name="ResearchAgent",
    )

    assert calls == [("context_mode", {"url": "https://example.com", "action": "fetch_and_index"})]
    assert result == {
        "action": "context_mode.fetch_and_index",
        "backend": "mcp",
        "server": "context_mode",
        "text": "indexed",
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


def test_mcp_service_confirmed_github_write_issue_routes_create_issue():
    calls = []

    def fake_runner(server, params):
        calls.append((server, params))
        return "created"

    service = McpCapabilityService(runner=fake_runner)
    registry = service.build_registry()

    result = registry.invoke(
        "github.write_issue",
        {"owner": "owner", "repo": "repo", "title": "Bug", "body": "Details", "confirm": True},
        agent_name="CodingAgent",
    )

    assert calls == [
        (
            "github",
            {
                "owner": "owner",
                "repo": "repo",
                "title": "Bug",
                "body": "Details",
                "confirm": True,
                "action": "create_issue",
            },
        )
    ]
    assert result == {
        "action": "github.write_issue",
        "backend": "mcp",
        "server": "github",
        "text": "created",
    }


def test_mcp_service_invokes_tavily_research_capabilities():
    calls = []

    def fake_runner(server, params):
        calls.append((server, params))
        return "research result"

    service = McpCapabilityService(runner=fake_runner)
    registry = service.build_registry()

    search = registry.invoke(
        "web_research.search",
        {"query": "latest f1 standings", "max_results": 5},
        agent_name="ResearchAgent",
    )
    answer = registry.invoke(
        "web_research.answer",
        {"query": "who leads f1 standings"},
        agent_name="VellumAgent",
    )

    assert calls == [
        ("tavily", {"action": "search", "query": "latest f1 standings", "max_results": 5}),
        ("tavily", {"action": "answer", "query": "who leads f1 standings"}),
    ]
    assert search["action"] == "web_research.search"
    assert answer["server"] == "tavily"


def test_mcp_service_invokes_firecrawl_extraction_capabilities():
    calls = []

    def fake_runner(server, params):
        calls.append((server, params))
        return "page content"

    service = McpCapabilityService(runner=fake_runner)
    registry = service.build_registry()

    fetch = registry.invoke(
        "web_extract.fetch",
        {"url": "https://example.com/article"},
        agent_name="MemoryAgent",
    )
    crawl = registry.invoke(
        "web_extract.crawl",
        {"url": "https://example.com/docs", "limit": 10},
        agent_name="ResearchAgent",
    )
    extract = registry.invoke(
        "web_extract.extract",
        {"url": "https://example.com/product", "schema": {"name": "string"}},
        agent_name="VellumAgent",
    )

    assert calls == [
        ("firecrawl", {"action": "fetch", "url": "https://example.com/article"}),
        ("firecrawl", {"action": "crawl", "url": "https://example.com/docs", "limit": 10}),
        ("firecrawl", {"action": "extract", "url": "https://example.com/product", "schema": {"name": "string"}}),
    ]
    assert fetch["server"] == "firecrawl"
    assert crawl["backend"] == "mcp"
    assert extract["action"] == "web_extract.extract"


def test_mcp_default_runner_works_inside_active_event_loop(monkeypatch):
    calls = []

    def fake_run_tools(requests):
        calls.append(requests)
        return [SimpleNamespace(result="thread-ok")]

    monkeypatch.setattr("agent.mcp.client.run_tools", fake_run_tools)

    async def run_default_runner():
        return McpCapabilityService._default_runner("context7", {"action": "resolve"})

    result = asyncio.run(run_default_runner())

    assert result == "thread-ok"
    assert calls == [[{"server": "context7", "params": {"action": "resolve"}}]]
