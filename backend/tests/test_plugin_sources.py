import json
from pathlib import Path

from agent.plugins.sources import CodexPluginSource, LooseSkillBundleSource


def test_codex_plugin_source_reads_apps_mcp_and_skill_ownership(tmp_path: Path):
    plugin = tmp_path / "cache" / "analytics" / "1.0.0"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / "skills" / "analyze").mkdir(parents=True)
    (plugin / "skills" / "analyze" / "SKILL.md").write_text(
        "---\nname: analyze\ndescription: Analyze data\n---\n# Analyze\n",
        encoding="utf-8",
    )
    (plugin / ".app.json").write_text(
        json.dumps({"apps": {"drive": {"id": "drive-id", "optional": True}}}),
        encoding="utf-8",
    )
    (plugin / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"widgets": {"command": "node"}}}),
        encoding="utf-8",
    )
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "analytics",
                "version": "1.0.0",
                "description": "Analyze",
                "skills": "./skills",
                "apps": "./.app.json",
                "mcpServers": "./.mcp.json",
                "interface": {
                    "displayName": "Analytics",
                    "developerName": "OpenAI",
                    "category": "Data",
                    "capabilities": ["Read", "Write"],
                },
            }
        ),
        encoding="utf-8",
    )

    records = CodexPluginSource([tmp_path / "cache"]).discover()

    assert len(records) == 1
    assert records[0].id == "analytics"
    assert records[0].skills_root == plugin / "skills"
    assert records[0].apps == [{"name": "drive", "id": "drive-id", "optional": True}]
    assert records[0].mcp_connectors == [{"name": "widgets", "command": "node"}]


def test_codex_plugin_source_rejects_declared_path_escape(tmp_path: Path):
    plugin = tmp_path / "cache" / "unsafe" / "1.0.0"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "unsafe", "skills": "../../../../outside"}),
        encoding="utf-8",
    )

    record = CodexPluginSource([tmp_path / "cache"]).discover()[0]

    assert record.skills_root is None


def test_loose_skill_bundle_exposes_only_named_installed_skills(tmp_path: Path):
    (tmp_path / "tdd").mkdir()
    (tmp_path / "tdd" / "SKILL.md").write_text("# TDD", encoding="utf-8")
    source = LooseSkillBundleSource(
        plugin_id="matt",
        name="Matt",
        root=tmp_path,
        skill_names=["tdd", "missing"],
        description="Engineering skills",
        developer="Matt Pocock",
    )

    assert source.discover()[0].id == "matt"
    assert source.skill_roots() == {tmp_path / "tdd": "matt"}
