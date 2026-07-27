from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent import api
from agent.plugins.registry import PluginRegistry


def _write_plugin(root: Path, plugin_id: str, *, required: bool = False) -> None:
    plugin = root / "connectors" / plugin_id
    skill = plugin / "skills" / f"{plugin_id}-skill"
    skill.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        f"id: {plugin_id}\n"
        f"name: {plugin_id.title()}\n"
        "type: connector\n"
        "category: Connectors\n"
        f"required: {'true' if required else 'false'}\n",
        encoding="utf-8",
    )
    (skill / "SKILL.md").write_text(
        f"---\nname: {plugin_id}-skill\ndescription: Use {plugin_id}\n---\n# Skill\n",
        encoding="utf-8",
    )


class _Agent:
    async def aclose(self) -> None:
        return None


def _status(plugin_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        model_dump=lambda: {
            "id": plugin_id,
            "name": plugin_id,
            "type": "connector",
            "category": "Connectors",
            "configured": True,
            "status": "ready",
            "notes": "ready",
            "capabilities": [],
        }
    )


def test_plugin_api_lists_owned_skills_and_persists_state(monkeypatch, tmp_path: Path):
    plugins = tmp_path / "plugins"
    _write_plugin(plugins, "demo")
    registry = PluginRegistry(plugins, state_path=tmp_path / "state.json")
    monkeypatch.setattr(api, "_plugin_registry_singleton", registry)
    monkeypatch.setattr(api, "_skill_surface_singleton", None)
    monkeypatch.setattr(api, "agent", _Agent())
    monkeypatch.setattr(api, "mcp_health", lambda probe=False: {"mcp_servers": []})
    monkeypatch.setattr(api, "memory_orchestrator_plugin_status", lambda _value: _status("memory"))
    monkeypatch.setattr(api, "agent_reach_plugin_status", lambda: _status("agent-reach"))
    monkeypatch.setattr(
        api,
        "portable_spotify_status",
        lambda: {
            "id": "spotify",
            "name": "Spotify",
            "configured": False,
            "status": "not_configured",
        },
    )

    with TestClient(api.app) as client:
        before = client.get("/api/plugins")
        disabled = client.post("/api/plugins/demo/state", json={"enabled": False})
        after = client.get("/api/plugins")

    assert before.status_code == 200
    demo = next(item for item in before.json()["plugins"] if item["id"] == "demo")
    assert demo["skills"][0]["owner_plugin"] == "demo"
    assert disabled.status_code == 200
    assert disabled.json()["plugin"]["enabled"] is False
    disabled_demo = next(item for item in after.json()["plugins"] if item["id"] == "demo")
    assert disabled_demo["status"] == "disabled"
    assert registry.skill_roots() == {}


def test_plugin_api_refuses_to_disable_required_plugin(monkeypatch, tmp_path: Path):
    plugins = tmp_path / "plugins"
    _write_plugin(plugins, "core", required=True)
    monkeypatch.setattr(
        api,
        "_plugin_registry_singleton",
        PluginRegistry(plugins, state_path=tmp_path / "state.json"),
    )

    with TestClient(api.app) as client:
        response = client.post("/api/plugins/core/state", json={"enabled": False})

    assert response.status_code == 409
    assert "required" in response.json()["detail"]
