from pathlib import Path

from agent.skills.registry import SkillRegistry


def test_owned_external_skill_reports_plugin_owner(tmp_path: Path):
    local = tmp_path / "local"
    plugin_skills = tmp_path / "plugin-skills"
    package = plugin_skills / "demo"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Plugin skill\n---\n# Demo\n",
        encoding="utf-8",
    )

    registry = SkillRegistry(
        local_root=local,
        owned_external_dirs={plugin_skills: "demo-plugin"},
    )

    entry = registry.list_skills()[0]
    assert entry.owner_plugin == "demo-plugin"
    assert registry.view("demo").owner_plugin == "demo-plugin"
