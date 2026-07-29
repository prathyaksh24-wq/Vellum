import json
from pathlib import Path

import pytest

from agent.mcp.plugin_runtime import (
    PluginMcpRuntime,
    PluginMcpRuntimeError,
)
from agent.plugins.registry import PluginRegistry
from agent.plugins.sources import CodexPluginSource
from agent.graph.agent import core_tool_registry
from agent.tools import plugin_mcp as plugin_mcp_module


def _plugin(tmp_path: Path, connector: dict) -> tuple[PluginRegistry, Path]:
    root = tmp_path / "cache" / "demo" / "1.0.0"
    (root / ".codex-plugin").mkdir(parents=True)
    (root / "mcp").mkdir()
    (root / "mcp" / "server.mjs").write_text("", encoding="utf-8")
    (root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"demo-server": connector}}),
        encoding="utf-8",
    )
    (root / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "1.0.0",
                "mcpServers": "./.mcp.json",
                "interface": {"displayName": "Demo"},
            }
        ),
        encoding="utf-8",
    )
    registry = PluginRegistry(
        tmp_path / "portable",
        state_path=tmp_path / "state.json",
        sources=[CodexPluginSource([tmp_path / "cache"])],
    )
    return registry, root


def test_runtime_resolves_stdio_args_inside_plugin_root(tmp_path: Path) -> None:
    registry, root = _plugin(
        tmp_path,
        {"command": "node", "args": ["./mcp/server.mjs", "--stdio"]},
    )

    connector = PluginMcpRuntime(registry).connectors()[0]

    assert connector.plugin_id == "demo"
    assert connector.transport == "stdio"
    assert connector.command == "node"
    assert connector.args[0] == str((root / "mcp" / "server.mjs").resolve())
    assert connector.cwd == root.resolve()


def test_runtime_rejects_stdio_path_escape(tmp_path: Path) -> None:
    registry, _ = _plugin(
        tmp_path,
        {"command": "node", "args": ["../../../../outside.mjs"]},
    )

    with pytest.raises(PluginMcpRuntimeError, match="outside its plugin root"):
        PluginMcpRuntime(registry).connectors()


def test_runtime_does_not_expose_disabled_plugin_connectors(tmp_path: Path) -> None:
    registry, _ = _plugin(tmp_path, {"url": "https://mcp.example.test/mcp"})
    registry.set_enabled("demo", False)

    assert PluginMcpRuntime(registry).connectors() == []


@pytest.mark.asyncio
async def test_runtime_allows_annotated_read_only_tool_without_confirmation(tmp_path: Path) -> None:
    registry, _ = _plugin(tmp_path, {"url": "https://mcp.example.test/mcp"})

    class FakeTransport:
        async def list_tools(self, connector):
            return [
                {
                    "name": "lookup",
                    "description": "Look up public data",
                    "input_schema": {"type": "object"},
                    "read_only": True,
                }
            ]

        async def call_tool(self, connector, tool_name, arguments):
            return f"{tool_name}:{arguments['query']}"

    runtime = PluginMcpRuntime(registry, transport=FakeTransport())

    result = await runtime.call_tool(
        "demo",
        "demo-server",
        "lookup",
        {"query": "public docs"},
    )

    assert result == "lookup:public docs"


@pytest.mark.asyncio
async def test_runtime_requires_confirmation_for_untrusted_mutation(tmp_path: Path) -> None:
    registry, _ = _plugin(tmp_path, {"url": "https://mcp.example.test/mcp"})

    class FakeTransport:
        async def list_tools(self, connector):
            return [{"name": "delete_record", "read_only": False}]

        async def call_tool(self, connector, tool_name, arguments):
            return "deleted"

    runtime = PluginMcpRuntime(registry, transport=FakeTransport())

    with pytest.raises(PluginMcpRuntimeError, match="requires confirmation"):
        await runtime.call_tool("demo", "demo-server", "delete_record", {"id": "1"})


@pytest.mark.asyncio
async def test_runtime_blocks_red_tool_arguments_before_transport(tmp_path: Path) -> None:
    registry, _ = _plugin(tmp_path, {"url": "https://mcp.example.test/mcp"})

    class FakeTransport:
        async def list_tools(self, connector):
            return [{"name": "lookup", "read_only": True}]

        async def call_tool(self, connector, tool_name, arguments):
            raise AssertionError("transport must not receive RED arguments")

    runtime = PluginMcpRuntime(registry, transport=FakeTransport())

    with pytest.raises(PluginMcpRuntimeError, match="Withheld"):
        await runtime.call_tool(
            "demo",
            "demo-server",
            "lookup",
            {"query": "password=super-secret"},
        )


def test_reasoning_agent_exposes_plugin_mcp_as_write_capability() -> None:
    record = core_tool_registry().get("plugin_mcp")

    assert record.access.value == "write"
    assert record.runtime_tool.name == "plugin_mcp"


def test_langchain_tool_invokes_async_runtime_from_sync_registry(monkeypatch) -> None:
    class FakeRuntime:
        async def list_tools(self, plugin_id, connector):
            return [{"name": "lookup", "read_only": True}]

    monkeypatch.setattr(plugin_mcp_module, "_runtime", lambda: FakeRuntime())

    result = plugin_mcp_module.plugin_mcp.invoke(
        {
            "action": "list_tools",
            "plugin_id": "demo",
            "connector": "demo-server",
        }
    )

    assert json.loads(result)["tools"][0]["name"] == "lookup"


def test_public_connector_metadata_hides_paths_and_url_queries(tmp_path: Path) -> None:
    registry, root = _plugin(
        tmp_path,
        {
            "command": "./mcp/server.mjs",
            "args": [],
        },
    )
    connector = PluginMcpRuntime(registry).connectors()[0]

    assert connector.public()["command"] == "server.mjs"
    assert str(root) not in json.dumps(connector.public())

    registry, _ = _plugin(
        tmp_path / "http",
        {"url": "https://mcp.example.test/mcp?token=private"},
    )
    assert PluginMcpRuntime(registry).connectors()[0].public()["url"] == (
        "https://mcp.example.test/mcp"
    )
