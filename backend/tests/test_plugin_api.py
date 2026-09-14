from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent import api
from agent.app_actions.models import AppActionDefinition, SurfacePresentation, UISurfaceDefinition
from agent.app_actions.runtime import AppActionRuntime
from agent.plugins.contributions import (
    PluginActionContribution,
    PluginContribution,
    PluginSurfaceContribution,
)
from agent.plugins.registry import PluginRegistry


def _write_plugin(root: Path, plugin_id: str, *, required: bool = False) -> None:
    plugin = root / "connectors" / plugin_id
    skill = plugin / "skills" / f"{plugin_id}-skill"
    skill.mkdir(parents=True)
    (plugin / "mcp").mkdir()
    (plugin / "mcp" / "server.mjs").write_text("", encoding="utf-8")
    (plugin / "plugin.yaml").write_text(
        f"id: {plugin_id}\n"
        f"name: {plugin_id.title()}\n"
        "type: connector\n"
        "category: Connectors\n"
        f"required: {'true' if required else 'false'}\n"
        "mcp_connectors:\n"
        "  - name: demo-mcp\n"
        "    command: node\n"
        "    args:\n"
        "      - ./mcp/server.mjs\n",
        encoding="utf-8",
    )
    (skill / "SKILL.md").write_text(
        f"---\nname: {plugin_id}-skill\ndescription: Use {plugin_id}\n---\n# Skill\n",
        encoding="utf-8",
    )


class _Agent:
    def __init__(self) -> None:
        self.invalidated = False

    async def aclose(self) -> None:
        return None

    def invalidate(self) -> None:
        self.invalidated = True


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
    action_runtime = AppActionRuntime(plugin_registry=registry)
    action_runtime.register_plugin_contribution(PluginContribution(
        owner="demo",
        actions=(PluginActionContribution(
            definition=AppActionDefinition(
                id="demo.run",
                version="1",
                owner="demo",
                plugin_id="demo",
                title="Run demo",
                description="Run the demo action.",
                scope="conversation",
                access_class="write",
                confirmation_rule="none",
                executor_location="server",
                supports_undo=False,
                idempotent=True,
                argument_schema={"type": "object"},
                result_schema={"type": "object"},
                ui_reference="demo.panel",
                audit_label="demo.run",
            ),
            adapter=lambda _payload: {"changed": True},
        ),),
        surfaces=(PluginSurfaceContribution(
            definition=UISurfaceDefinition(
                reference="demo.panel",
                owner="demo",
                plugin_id="demo",
                title="Demo panel",
                aliases=["demo panel"],
                default_presentation=SurfacePresentation(visible=True, location="right"),
                supported_locations=["right"],
            ),
        ),),
    ))
    monkeypatch.setattr(api, "_app_action_runtime", action_runtime)
    monkeypatch.setattr(api, "_skill_surface_singleton", None)
    agent = _Agent()
    monkeypatch.setattr(api, "agent", agent)
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
    assert demo["mcp_connectors"][0]["transport"] == "stdio"
    assert demo["mcp_connectors"][0]["configured"] is True
    assert demo["mcp_connectors"][0]["status"] == "configured"
    assert demo["app_actions"][0]["id"] == "demo.run"
    assert demo["app_actions"][0]["available"] is True
    assert demo["ui_surfaces"][0]["reference"] == "demo.panel"
    assert demo["ui_surfaces"][0]["available"] is True
    assert disabled.status_code == 200
    assert disabled.json()["plugin"]["enabled"] is False
    disabled_demo = next(item for item in after.json()["plugins"] if item["id"] == "demo")
    assert disabled_demo["status"] == "disabled"
    assert disabled_demo["app_actions"][0]["available"] is False
    assert disabled_demo["ui_surfaces"][0]["available"] is False
    assert registry.skill_roots() == {}
    assert agent.invalidated is True


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
