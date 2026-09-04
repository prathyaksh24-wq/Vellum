from pathlib import Path

import pytest

from agent.plugins.registry import PluginRegistry, PluginRegistryError
from agent.plugins.sources import PluginSourceRecord


def _write_plugin(root: Path, plugin_id: str, *, required: bool = False) -> Path:
    plugin = root / "connectors" / plugin_id
    skill = plugin / "skills" / f"{plugin_id}-skill"
    skill.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        f"id: {plugin_id}\n"
        f"name: {plugin_id.title()}\n"
        "type: connector\n"
        "category: Connectors\n"
        f"required: {'true' if required else 'false'}\n"
        "provides_tools:\n"
        f"  - {plugin_id}_search\n"
        "capabilities:\n"
        f"  - {plugin_id}.search\n",
        encoding="utf-8",
    )
    (skill / "SKILL.md").write_text(
        f"---\nname: {plugin_id}-skill\ndescription: Use {plugin_id}\n---\n# {plugin_id.title()}\n",
        encoding="utf-8",
    )
    return plugin


def test_registry_owns_plugin_children_and_persists_enablement(tmp_path: Path):
    plugins = tmp_path / "plugins"
    _write_plugin(plugins, "demo")
    state = tmp_path / "data" / "plugins" / "state.json"
    registry = PluginRegistry(plugins, state_path=state)

    record = registry.describe("demo")

    assert record["enabled"] is True
    assert record["tools"] == ["demo_search"]
    assert record["skills"] == [
        {
            "id": "demo-skill",
            "name": "demo-skill",
            "description": "Use demo",
            "owner_plugin": "demo",
            "enabled": True,
        }
    ]
    assert registry.skill_roots() == {plugins / "connectors" / "demo" / "skills": "demo"}

    registry.set_enabled("demo", False)

    restored = PluginRegistry(plugins, state_path=state)
    assert restored.is_enabled("demo") is False
    assert restored.skill_roots() == {}
    assert restored.describe("demo")["status"] == "disabled"


def test_required_plugin_cannot_be_disabled(tmp_path: Path):
    plugins = tmp_path / "plugins"
    _write_plugin(plugins, "core", required=True)
    registry = PluginRegistry(plugins, state_path=tmp_path / "state.json")

    with pytest.raises(PluginRegistryError, match="required"):
        registry.set_enabled("core", False)


def test_catalog_normalizes_mcp_servers_without_claiming_lifecycle_control(tmp_path: Path):
    registry = PluginRegistry(tmp_path / "plugins", state_path=tmp_path / "state.json")

    records = registry.catalog(
        mcp_servers=[{"name": "context7", "configured": True, "status": "probe_disabled"}]
    )

    assert records[0]["id"] == "context7"
    assert records[0]["type"] == "mcp"
    assert records[0]["manageable"] is False
    assert records[0]["mcp_connectors"][0]["id"] == "context7"


def test_catalog_snapshots_external_skill_roots_once(tmp_path: Path):
    class CountingSource:
        def __init__(self) -> None:
            self.skill_root_calls = 0

        def discover(self):
            return [
                PluginSourceRecord(
                    id=plugin_id,
                    name=plugin_id.title(),
                    version="1.0.0",
                    description="Test source",
                    category="Test",
                    developer="Test",
                    source="test",
                    root=tmp_path / plugin_id,
                )
                for plugin_id in ("first", "second")
            ]

        def skill_roots(self):
            self.skill_root_calls += 1
            return {}

    source = CountingSource()
    registry = PluginRegistry(
        tmp_path / "plugins",
        state_path=tmp_path / "state.json",
        sources=[source],
    )

    assert len(registry.catalog()) == 2
    assert source.skill_root_calls == 1
