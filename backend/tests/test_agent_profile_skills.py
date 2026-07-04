from pathlib import Path

from agent.profiles import AgentSkillLoader


def test_skill_loader_activates_ordered_agent_home_skills(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "sources.md").write_text(
        """---
id: sources
description: Prefer official sources
triggers: [latest, score]
negative_triggers: [fiction]
priority: 20
---
Use official sources first.
""",
        encoding="utf-8",
    )
    (skills / "tables.md").write_text(
        """---
id: tables
description: Use tables
triggers: [score]
priority: 10
---
Use a compact table.
""",
        encoding="utf-8",
    )

    activated = AgentSkillLoader(tmp_path).activate("latest score")

    assert [skill.id for skill in activated.skills] == ["tables", "sources"]
    assert activated.skill_hash
    assert AgentSkillLoader(tmp_path).activate("fiction score").skills == ()


def test_skill_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    content = "---\nid: same\ndescription: test\ntriggers: [x]\npriority: 1\n---\nDo x.\n"
    (skills / "a.md").write_text(content, encoding="utf-8")
    (skills / "b.md").write_text(content, encoding="utf-8")

    activated = AgentSkillLoader(tmp_path).activate("x")

    assert activated.skills == ()
    assert any("duplicate" in item for item in activated.diagnostics)
