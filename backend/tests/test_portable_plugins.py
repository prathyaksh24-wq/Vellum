from pathlib import Path

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
