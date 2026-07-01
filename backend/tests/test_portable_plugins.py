from pathlib import Path
import runpy

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


def test_spotify_manifest_declares_full_hermes_toolset():
    manifests = {item.id: item for item in discover_portable_plugins(Path("plugins"))}

    spotify = manifests["spotify"]

    assert spotify.type == "connector"
    assert spotify.category == "Connectors"
    assert spotify.capabilities == [
        "spotify.playback",
        "spotify.devices",
        "spotify.queue",
        "spotify.search",
        "spotify.playlists",
        "spotify.albums",
        "spotify.library",
    ]


def test_spotify_schemas_cover_expected_tools_and_playback_actions():
    namespace = runpy.run_path("plugins/connectors/spotify/schemas.py")

    schemas = namespace["ALL_SCHEMAS"]
    assert [schema["name"] for schema in schemas] == [
        "spotify_playback",
        "spotify_devices",
        "spotify_queue",
        "spotify_search",
        "spotify_playlists",
        "spotify_albums",
        "spotify_library",
    ]
    assert namespace["SPOTIFY_PLAYBACK"]["parameters"]["properties"]["action"]["enum"] == [
        "get_state",
        "get_currently_playing",
        "play",
        "pause",
        "next",
        "previous",
        "seek",
        "set_repeat",
        "set_shuffle",
        "set_volume",
        "recently_played",
    ]
    assert "save_current" in namespace["SPOTIFY_LIBRARY"]["parameters"]["properties"]["action"]["enum"]
