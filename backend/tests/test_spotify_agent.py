import json
from pathlib import Path
import subprocess
import sys

from agent.plugins import spotify_runtime
from agent.plugins.portable import PortablePluginContext, PortableRegisteredTool


def test_spotify_tools_absent_when_not_authenticated(monkeypatch):
    monkeypatch.setattr(spotify_runtime, "spotify_is_authenticated", lambda: False)

    assert spotify_runtime.portable_agent_tools() == []


def test_spotify_tools_present_when_authenticated(monkeypatch):
    monkeypatch.setattr(spotify_runtime, "spotify_is_authenticated", lambda: True)

    names = {tool.name for tool in spotify_runtime.portable_agent_tools()}

    assert names == {
        "spotify_playback",
        "spotify_devices",
        "spotify_queue",
        "spotify_search",
        "spotify_playlists",
        "spotify_albums",
        "spotify_library",
    }


def test_langchain_wrapper_calls_hermes_handler():
    record = PortableRegisteredTool(
        name="spotify_demo",
        toolset="spotify",
        schema={
            "name": "spotify_demo",
            "description": "Demo Spotify action.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
        handler=lambda args, **kwargs: json.dumps({"value": args["value"]}),
    )

    tool = spotify_runtime.as_langchain_tool(record)

    assert json.loads(tool.invoke({"value": "ok"})) == {"value": "ok"}


def test_registered_spotify_context_contains_connector_and_tools():
    ctx = spotify_runtime.registered_spotify_context()

    assert isinstance(ctx, PortablePluginContext)
    assert "spotify" in ctx.connectors
    assert len(ctx.tools) == 7


def test_spotify_runtime_imports_from_backend_working_directory():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from agent.plugins import spotify_runtime; print(spotify_runtime.PLUGIN_DIR)",
        ],
        cwd=Path("backend"),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "plugins" in result.stdout
    assert "spotify" in result.stdout
