from pathlib import Path

import pytest

from agent.plugins.portable import PortablePluginContext, discover_portable_plugins, load_portable_plugin


def test_discovers_hermes_style_agent_reach_and_memory_plugins():
    plugins = {plugin.id: plugin for plugin in discover_portable_plugins(Path("plugins"))}

    assert plugins["agent-reach"].category == "Connectors"
    assert plugins["agent-reach"].type == "connector"
    assert "x.search" in plugins["agent-reach"].capabilities
    assert plugins["memory-orchestrator"].category == "Memory"
    assert plugins["memory-orchestrator"].type == "system"
    assert "memory.run_dreaming" in plugins["memory-orchestrator"].capabilities


def test_portable_agent_reach_registers_existing_backend_connector():
    plugin = load_portable_plugin(Path("plugins/connectors/agent-reach"))
    ctx = PortablePluginContext()

    plugin.register(ctx)

    connector = ctx.connectors["agent-reach"]
    assert connector["id"] == "agent-reach"
    assert connector["status_factory"] is not None
    assert connector["provider_factory"] is not None


def test_portable_memory_orchestrator_registers_existing_backend_system_plugin():
    plugin = load_portable_plugin(Path("plugins/memory/vellum-memory-orchestrator"))
    ctx = PortablePluginContext()

    plugin.register(ctx)

    system = ctx.system_plugins["memory-orchestrator"]
    assert system["id"] == "memory-orchestrator"
    assert system["status_factory"] is not None
    assert system["required"] is True


def test_portable_plugin_supports_relative_imports_and_register_tool(tmp_path):
    plugin_dir = tmp_path / "plugins" / "connectors" / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        "id: demo\nname: Demo\ntype: connector\ncategory: Connectors\n"
        "provides_tools:\n  - demo_echo\ncapabilities:\n  - demo.echo\n",
        encoding="utf-8",
    )
    (plugin_dir / "schemas.py").write_text(
        "ECHO = {'name': 'demo_echo', 'description': 'Echo text', "
        "'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, "
        "'required': ['text']}}\n",
        encoding="utf-8",
    )
    (plugin_dir / "tools.py").write_text(
        "import json\ndef echo(args, **kwargs): return json.dumps({'text': args['text']})\n",
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(
        "from . import schemas, tools\n"
        "def register(ctx):\n"
        "    ctx.register_tool(name='demo_echo', toolset='demo', "
        "schema=schemas.ECHO, handler=tools.echo)\n",
        encoding="utf-8",
    )

    ctx = PortablePluginContext()
    load_portable_plugin(plugin_dir).register(ctx)

    assert ctx.tools["demo_echo"].toolset == "demo"
    assert ctx.tools["demo_echo"].handler({"text": "hello"}) == '{"text": "hello"}'


def test_register_tool_rejects_duplicate_names():
    ctx = PortablePluginContext()
    schema = {"name": "same", "description": "x", "parameters": {"type": "object"}}
    ctx.register_tool(name="same", toolset="one", schema=schema, handler=lambda args: "{}")

    with pytest.raises(ValueError, match="already registered"):
        ctx.register_tool(name="same", toolset="two", schema=schema, handler=lambda args: "{}")
